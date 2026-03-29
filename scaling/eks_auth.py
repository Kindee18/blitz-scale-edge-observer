"""EKS Authentication Module for Lambda-based Kubernetes API Access.

This module provides proper EKS token authentication using the AWS STS
token generator pattern, enabling Lambda functions to authenticate with
EKS clusters without relying on local kubeconfig files.
"""

import base64
import logging
import os

import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from kubernetes import client, config
from kubernetes.client import Configuration

logger = logging.getLogger("EKSAuth")
logger.setLevel(logging.INFO)

EKS_CLUSTER_NAME = os.getenv("EKS_CLUSTER_NAME", "blitz-edge-cluster")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")


class EKSAuthError(Exception):
    """Custom exception for EKS authentication failures."""

    pass


def get_eks_token(cluster_name: str, region: str = AWS_REGION) -> str:
    """Generate an EKS authentication token using STS.

    This uses the same mechanism as `aws eks get-token` but implemented
    in pure Python for use in Lambda environments.

    Args:
        cluster_name: Name of the EKS cluster
        region: AWS region where the cluster is located

    Returns:
        A Kubernetes authentication token prefixed with 'k8s-aws-v1.'

    Raises:
        EKSAuthError: If token generation fails
    """
    try:
        # Create the STS presigned URL
        boto3.client("sts", region_name=region)

        # The token is a signed URL to STS GetCallerIdentity
        # with the cluster ID as the audience
        service_id = "sts"
        url = f"https://{service_id}.{region}.amazonaws.com/?Action=GetCallerIdentity&Version=2011-06-15"

        # Create the request and sign it with SigV4
        request = AWSRequest(method="GET", url=url)

        # Sign the request
        session = boto3.Session()
        credentials = session.get_credentials()
        frozen_credentials = credentials.get_frozen_credentials()

        signer = SigV4Auth(
            boto3.Session(
                aws_access_key_id=frozen_credentials.access_key,
                aws_secret_access_key=frozen_credentials.secret_key,
                aws_session_token=frozen_credentials.token,
                region_name=region,
            ).get_credentials(),
            service_id,
            region,
        )
        signer.add_auth(request)

        # The token is the presigned URL, base64 encoded with the k8s-aws-v1 prefix
        presigned_url = request.url
        encoded_url = (
            base64.urlsafe_b64encode(presigned_url.encode("utf-8"))
            .decode("utf-8")
            .rstrip("=")
        )

        token = f"k8s-aws-v1.{encoded_url}"
        logger.info(f"Generated EKS token for cluster: {cluster_name}")
        return token

    except Exception as e:
        logger.error(f"Failed to generate EKS token: {e}")
        raise EKSAuthError(f"Token generation failed: {e}") from e


def get_kubernetes_config(
    cluster_name: str = EKS_CLUSTER_NAME,
    region: str = AWS_REGION,
    ca_cert_data: str = None,
) -> tuple:
    """Get configured Kubernetes API clients for an EKS cluster.

    This function retrieves the cluster endpoint and CA certificate from AWS,
    generates an authentication token, and returns configured Kubernetes API clients.

    Args:
        cluster_name: Name of the EKS cluster
        region: AWS region where the cluster is located
        ca_cert_data: Optional base64-encoded CA certificate data. If not provided,
                     it will be fetched from EKS.

    Returns:
        Tuple of (AppsV1Api, CoreV1Api, Configuration) for interacting with the cluster

    Raises:
        EKSAuthError: If cluster connection or authentication fails
    """
    try:
        # Get cluster info from EKS
        eks_client = boto3.client("eks", region_name=region)
        response = eks_client.describe_cluster(name=cluster_name)
        cluster = response["cluster"]

        endpoint = cluster["endpoint"]

        # Get CA cert - in Lambda, we need to write it to a temp file
        if ca_cert_data is None:
            ca_cert_data = cluster["certificateAuthority"]["data"]

        # Decode and write CA cert to temp file
        import tempfile

        with tempfile.NamedTemporaryFile(delete=False, suffix=".crt") as ca_file:
            ca_cert_bytes = base64.b64decode(ca_cert_data)
            ca_file.write(ca_cert_bytes)
            ca_cert_path = ca_file.name

        # Generate authentication token
        token = get_eks_token(cluster_name, region)

        # Configure Kubernetes client
        configuration = Configuration()
        configuration.host = endpoint
        configuration.ssl_ca_cert = ca_cert_path
        configuration.api_key["authorization"] = token
        configuration.api_key_prefix["authorization"] = "Bearer"

        # Set timeouts
        configuration.connect_timeout = 10
        configuration.read_timeout = 30

        client.Configuration.set_default(configuration)

        # Return API clients
        apps_v1 = client.AppsV1Api()
        core_v1 = client.CoreV1Api()

        logger.info(
            f"Successfully configured Kubernetes client for cluster: {cluster_name}"
        )
        return apps_v1, core_v1, configuration

    except client.exceptions.ApiException as e:
        logger.error(f"Kubernetes API error: {e}")
        raise EKSAuthError(f"Kubernetes API error: {e}") from e
    except Exception as e:
        logger.error(f"Failed to configure Kubernetes client: {e}")
        raise EKSAuthError(f"Configuration failed: {e}") from e


def test_cluster_connection(
    apps_v1: client.AppsV1Api, core_v1: client.CoreV1Api
) -> dict:
    """Test the cluster connection by listing namespaces and deployments.

    Args:
        apps_v1: Configured AppsV1Api client
        core_v1: Configured CoreV1Api client

    Returns:
        Dictionary with connection status and cluster info
    """
    try:
        # Try to list namespaces to verify connection
        namespaces = core_v1.list_namespace()
        ns_count = len(namespaces.items)

        # Try to list deployments in default namespace
        deployments = apps_v1.list_namespaced_deployment(namespace="default")
        deployment_count = len(deployments.items)

        return {
            "connected": True,
            "namespaces": ns_count,
            "deployments_in_default": deployment_count,
            "error": None,
        }

    except Exception as e:
        logger.error(f"Cluster connection test failed: {e}")
        return {
            "connected": False,
            "namespaces": 0,
            "deployments_in_default": 0,
            "error": str(e),
        }


# Backwards compatibility - maintain existing interface
def get_kube_config_local() -> tuple:
    """Get Kubernetes config from local kubeconfig (for local development).

    Returns:
        Tuple of (AppsV1Api, CoreV1Api)
    """
    config.load_kube_config()
    return client.AppsV1Api(), client.CoreV1Api()
