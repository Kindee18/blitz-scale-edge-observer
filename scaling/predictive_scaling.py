import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import List, Tuple

import boto3
from botocore.config import Config
from kubernetes import client, config

# Configure Logging
logger = logging.getLogger("PredictiveScaler")
logger.setLevel(logging.INFO)

EKS_CLUSTER_NAME = os.getenv("EKS_CLUSTER_NAME", "blitz-edge-cluster")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
NAMESPACE = "karpenter-buffer"
DEPLOYMENT_NAME = "spike-buffer"


def get_kube_config():
    """Authenticates with EKS and loads kubernetes configuration."""
    eks = boto3.client("eks", region_name=AWS_REGION)
    cluster = eks.describe_cluster(name=EKS_CLUSTER_NAME)["cluster"]

    # In Lambda, we use the IAM role token
    # For local/script usage, we assume AWS credentials are set
    configuration = client.Configuration()
    configuration.host = cluster["endpoint"]
    configuration.ssl_ca_cert = (
        None  # In prod, write cluster['certificateAuthority']['data'] to a temp file
    )

    # Get token via STS/EKS token generator
    # requires 'aws' CLI or botocore internal
    sts = boto3.client("sts")
    sts.get_caller_identity()  # Dummy, in reality use EKS token generator API

    # Simplified for the walkthrough/prototype implementation:
    config.load_kube_config()  # Assuming local kubeconfig or cluster role
    return client.AppsV1Api(), client.CoreV1Api()


def load_game_schedule_from_s3(bucket: str, key: str) -> list:
    """Loads game schedule JSON from S3 to find upcoming kickoffs.

    Args:
        bucket: S3 bucket name containing the schedule
        key: S3 object key for the schedule JSON

    Returns:
        List of game schedule entries, or empty list if loading fails
    """
    s3 = boto3.client(
        "s3", region_name=AWS_REGION, config=Config(retries={"max_attempts": 3})
    )
    try:
        response = s3.get_object(Bucket=bucket, Key=key)
        schedule = json.loads(response["Body"].read().decode("utf-8"))
        logger.info(f"Loaded {len(schedule)} games from s3://{bucket}/{key}")
        return schedule
    except Exception as e:
        logger.error(f"Failed to load schedule from S3: {e}")
        return []


def is_spike_imminent(schedule: list, lead_time_minutes=30) -> Tuple[bool, List[dict]]:
    """Checks if any game kicks off within the lead time.

    Args:
        schedule: List of game schedule entries with 'kickoff_time' field
        lead_time_minutes: How many minutes before kickoff to trigger scaling

    Returns:
        Tuple of (spike_imminent: bool, approaching_games: list)
        - spike_imminent: True if any game starts within lead time
        - approaching_games: List of games that are approaching (within lead time)
    """
    now = datetime.now(timezone.utc)
    approaching_games = []

    for game in schedule:
        kickoff = datetime.fromisoformat(game["kickoff_time"].replace("Z", "+00:00"))
        time_diff = kickoff - now
        if timedelta(minutes=0) <= time_diff <= timedelta(minutes=lead_time_minutes):
            approaching_games.append(game)

    spike_imminent = len(approaching_games) > 0
    if spike_imminent:
        logger.info(
            f"Found {len(approaching_games)} games starting within {lead_time_minutes} minutes"
        )

    return spike_imminent, approaching_games


def trigger_karpenter_scale_up(apps_v1, core_v1):
    """Creates a dummy 'pause' deployment to force Karpenter to provision nodes."""
    logger.info(f"Triggering pre-scale for cluster {EKS_CLUSTER_NAME}")

    container = client.V1Container(
        name="pause",
        image="registry.k8s.io/pause:3.9",
        resources=client.V1ResourceRequirements(requests={"cpu": "1", "memory": "2Gi"}),
    )

    template = client.V1PodTemplateSpec(
        metadata=client.V1ObjectMeta(labels={"app": DEPLOYMENT_NAME}),
        spec=client.V1PodSpec(
            containers=[container], priority_class_name="low-priority"
        ),
    )

    spec = client.V1DeploymentSpec(
        replicas=10,  # 10 cores pre-buffered
        template=template,
        selector=client.V1LabelSelector(match_labels={"app": DEPLOYMENT_NAME}),
    )

    deployment = client.V1Deployment(
        api_version="apps/v1",
        kind="Deployment",
        metadata=client.V1ObjectMeta(name=DEPLOYMENT_NAME),
        spec=spec,
    )

    try:
        apps_v1.create_namespaced_deployment(namespace="default", body=deployment)
        logger.info("Successfully created pre-scale buffer pods.")
    except client.exceptions.ApiException as e:
        if e.status == 409:  # Already exists
            apps_v1.patch_namespaced_deployment(
                name=DEPLOYMENT_NAME,
                namespace="default",
                body={"spec": {"replicas": 10}},
            )
            logger.info("Pre-scale buffer already exists. Updated replicas.")
        else:
            logger.error(f"K8s API error: {e}")


def trigger_karpenter_scale_down(apps_v1):
    """Scale down the buffer to allow Karpenter to consolidate nodes."""
    logger.info(f"Scaling down buffer pods for cluster {EKS_CLUSTER_NAME}")
    try:
        apps_v1.patch_namespaced_deployment(
            name=DEPLOYMENT_NAME, namespace="default", body={"spec": {"replicas": 0}}
        )
    except client.exceptions.ApiException as e:
        if e.status == 404:
            logger.info("No buffer deployment found to scale down.")
        else:
            logger.error(f"K8s API error: {e}")


def main():
    apps_v1, core_v1 = get_kube_config()
    schedule_bucket = os.getenv("SCHEDULE_BUCKET", "blitz-edge-schedules")
    schedule_key = os.getenv("SCHEDULE_KEY", "schedule.json")
    schedule = load_game_schedule_from_s3(schedule_bucket, schedule_key)

    if is_spike_imminent(schedule, lead_time_minutes=30):
        logger.info("Spike is imminent. Pre-scaling cluster...")
        trigger_karpenter_scale_up(apps_v1, core_v1)
    else:
        logger.info("No immediate spikes or games active. Normalizing cluster scale...")
        trigger_karpenter_scale_down(apps_v1)


if __name__ == "__main__":
    main()
