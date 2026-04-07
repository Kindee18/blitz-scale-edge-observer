"""Scheduled Predictive Scaler Lambda Handler.

This module provides a Lambda-compatible entry point for the predictive scaling
functionality, including DynamoDB-based idempotency locking to prevent concurrent
scaling operations, comprehensive error handling, and CloudWatch metrics emission.
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple

import boto3
from botocore.config import Config
from eks_auth import EKSAuthError, get_kubernetes_config, test_cluster_connection
from predictive_scaling import (
    is_spike_imminent,
    trigger_karpenter_scale_down,
    trigger_karpenter_scale_up,
)

# Configure structured logging
logger = logging.getLogger("ScheduledScaler")
logger.setLevel(logging.INFO)

# Environment configuration
EKS_CLUSTER_NAME = os.getenv("EKS_CLUSTER_NAME", "blitz-edge-cluster")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
SCHEDULE_S3_BUCKET = os.getenv("SCHEDULE_S3_BUCKET")
SCHEDULE_S3_KEY = os.getenv("SCHEDULE_S3_KEY", "game_schedules/nfl_today.json")
DYNAMODB_LOCK_TABLE = os.getenv("DYNAMODB_LOCK_TABLE", "blitz-scaling-locks")
LOCK_TTL_SECONDS = int(os.getenv("LOCK_TTL_SECONDS", "300"))  # 5 minutes
LEAD_TIME_MINUTES = int(os.getenv("LEAD_TIME_MINUTES", "45"))
DRY_RUN_MODE = os.getenv("DRY_RUN_MODE", "false").lower() == "true"
ENDPOINT_URL = os.getenv("ENDPOINT_URL")

# AWS clients with optimized config
aws_config = Config(retries={"max_attempts": 3, "mode": "adaptive"})
dynamodb = boto3.resource(
    "dynamodb", region_name=AWS_REGION, endpoint_url=ENDPOINT_URL, config=aws_config
)
cw = boto3.client(
    "cloudwatch", region_name=AWS_REGION, endpoint_url=ENDPOINT_URL, config=aws_config
)


def emit_metric(name: str, value: float, unit: str = "Count", dimensions: list = None):
    """Emit CloudWatch metric for observability."""
    try:
        metric_data = {
            "MetricName": name,
            "Value": value,
            "Unit": unit,
            "Timestamp": datetime.now(timezone.utc),
        }
        if dimensions:
            metric_data["Dimensions"] = dimensions

        cw.put_metric_data(
            Namespace="BlitzScale/PredictiveScaling", MetricData=[metric_data]
        )
    except Exception as e:
        logger.warning(f"Failed to emit metric {name}: {e}")


def acquire_lock(lock_id: str, lambda_request_id: str) -> Tuple[bool, Optional[str]]:
    """Acquire DynamoDB lock for idempotency."""
    table = dynamodb.Table(DYNAMODB_LOCK_TABLE)
    now = datetime.now(timezone.utc)
    expiration_time = int(now.timestamp()) + LOCK_TTL_SECONDS

    try:
        table.put_item(
            Item={
                "lock_id": lock_id,
                "request_id": lambda_request_id,
                "acquired_at": now.isoformat(),
                "expiration_time": expiration_time,
                "status": "acquired",
            },
            ConditionExpression="attribute_not_exists(lock_id) OR expiration_time < :now",
            ExpressionAttributeValues={":now": int(now.timestamp())},
        )
        logger.info(f"Lock acquired: {lock_id}")
        emit_metric("ScalingLockAcquired", 1)
        return True, None

    except dynamodb.meta.client.exceptions.ConditionalCheckFailedException:
        try:
            response = table.get_item(Key={"lock_id": lock_id})
            item = response.get("Item", {})
            current_owner = item.get("request_id", "unknown")
            logger.info(f"Lock already held by: {current_owner}")
            emit_metric("ScalingLockContention", 1)
            return False, current_owner
        except Exception as e:
            logger.error(f"Failed to query lock owner: {e}")
            return False, "unknown"

    except Exception as e:
        logger.error(f"Failed to acquire lock: {e}")
        emit_metric("ScalingLockError", 1)
        return False, None


def release_lock(lock_id: str, lambda_request_id: str) -> bool:
    """Release the DynamoDB lock."""
    table = dynamodb.Table(DYNAMODB_LOCK_TABLE)

    try:
        table.delete_item(
            Key={"lock_id": lock_id},
            ConditionExpression="request_id = :request_id",
            ExpressionAttributeValues={":request_id": lambda_request_id},
        )
        logger.info(f"Lock released: {lock_id}")
        return True

    except dynamodb.meta.client.exceptions.ConditionalCheckFailedException:
        logger.warning(f"Cannot release lock {lock_id}: owned by different request")
        return False

    except Exception as e:
        logger.warning(
            f"Failed to release lock (will expire in {LOCK_TTL_SECONDS}s): {e}"
        )
        return False


def update_lock_status(lock_id: str, status: str, details: Dict = None):
    """Update lock status with operation results."""
    table = dynamodb.Table(DYNAMODB_LOCK_TABLE)

    try:
        update_expr = "SET #status = :status, updated_at = :now"
        expr_names = {"#status": "status"}
        expr_values = {
            ":status": status,
            ":now": datetime.now(timezone.utc).isoformat(),
        }

        if details:
            update_expr += ", details = :details"
            expr_values[":details"] = json.dumps(details)

        table.update_item(
            Key={"lock_id": lock_id},
            UpdateExpression=update_expr,
            ExpressionAttributeNames=expr_names,
            ExpressionAttributeValues=expr_values,
        )
    except Exception as e:
        logger.warning(f"Failed to update lock status: {e}")


def lambda_handler(event: Dict, context) -> Dict:
    """Main Lambda handler for scheduled predictive scaling.

    Triggered by EventBridge on a schedule (e.g., every 15 minutes).
    Checks for upcoming game kickoffs and scales the EKS cluster accordingly.
    """
    request_id = context.aws_request_id if context else "local-test"
    start_time = datetime.now(timezone.utc)

    logger.info(f"Starting predictive scaling check - Request ID: {request_id}")
    emit_metric(
        "ScalingInvocations",
        1,
        dimensions=[{"Name": "DryRun", "Value": str(DRY_RUN_MODE)}],
    )

    lock_id = f"spike-prep-{start_time.strftime('%Y-%m-%d')}"

    lock_acquired, current_owner = acquire_lock(lock_id, request_id)
    if not lock_acquired:
        logger.info(f"Lock already held by {current_owner}, skipping execution")
        emit_metric(
            "ScalingSkipped",
            1,
            "Count",
            [{"Name": "Reason", "Value": "LockContention"}],
        )
        return {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "status": "skipped",
                    "reason": "lock_contention",
                    "lock_owner": current_owner,
                }
            ),
        }

    result = {
        "status": "unknown",
        "dry_run": DRY_RUN_MODE,
        "actions_taken": [],
        "errors": [],
    }

    try:
        s3 = boto3.client("s3", endpoint_url=ENDPOINT_URL)
        try:
            response = s3.get_object(Bucket=SCHEDULE_S3_BUCKET, Key=SCHEDULE_S3_KEY)
            schedule = json.loads(response["Body"].read().decode("utf-8"))
        except Exception as e:
            logger.error(f"Error loading schedule from S3: {e}")
            result["errors"].append(f"S3 load: {str(e)}")
            result["status"] = "failed"
            return {"statusCode": 500, "body": json.dumps(result)}

        if not schedule:
            logger.warning("No games found in schedule")
            result["status"] = "no_games"
            return {"statusCode": 200, "body": json.dumps(result)}

        logger.info(f"Loaded {len(schedule)} games from schedule")

        spike_imminent, games_approaching = is_spike_imminent(
            schedule, lead_time_minutes=LEAD_TIME_MINUTES
        )

        if DRY_RUN_MODE:
            logger.info(
                f"DRY RUN: Would check for spike with lead time {LEAD_TIME_MINUTES}m"
            )
            logger.info(f"DRY RUN: {len(games_approaching)} games approaching")
            result["dry_run_actions"] = (
                [f"Would scale up for {len(games_approaching)} approaching games"]
                if games_approaching
                else ["Would scale down (no imminent games)"]
            )

        if spike_imminent:
            logger.info(
                f"Spike imminent! {len(games_approaching)} games starting within {LEAD_TIME_MINUTES} minutes"
            )
            result["approaching_games"] = games_approaching

            update_lock_status(lock_id, "scaling_up", {"games": games_approaching})

            if not DRY_RUN_MODE:
                try:
                    apps_v1, core_v1, _ = get_kubernetes_config(
                        cluster_name=EKS_CLUSTER_NAME, region=AWS_REGION
                    )

                    conn_test = test_cluster_connection(apps_v1, core_v1)
                    if not conn_test["connected"]:
                        raise EKSAuthError(
                            f"Cluster connection failed: {conn_test['error']}"
                        )

                    trigger_karpenter_scale_up(apps_v1, core_v1)
                    result["actions_taken"].append("scale_up")
                    result["status"] = "scaled_up"
                    emit_metric("ScalingScaleUp", len(games_approaching))
                    logger.info(
                        f"Successfully triggered scale-up for cluster {EKS_CLUSTER_NAME}"
                    )

                except EKSAuthError as e:
                    logger.error(f"EKS authentication failed: {e}")
                    result["errors"].append(f"EKS auth: {str(e)}")
                    result["status"] = "failed"
                    emit_metric(
                        "ScalingErrors",
                        1,
                        dimensions=[{"Name": "ErrorType", "Value": "EKSAuth"}],
                    )

                except Exception as e:
                    logger.error(f"Scale-up failed: {e}")
                    result["errors"].append(f"Scale-up: {str(e)}")
                    result["status"] = "failed"
                    emit_metric(
                        "ScalingErrors",
                        1,
                        dimensions=[{"Name": "ErrorType", "Value": "ScaleUp"}],
                    )
            else:
                result["status"] = "dry_run_scale_up"

        else:
            logger.info("No imminent spikes detected. Scaling down if needed.")

            update_lock_status(lock_id, "scaling_down")

            if not DRY_RUN_MODE:
                try:
                    apps_v1, _, _ = get_kubernetes_config(
                        cluster_name=EKS_CLUSTER_NAME, region=AWS_REGION
                    )
                    trigger_karpenter_scale_down(apps_v1)
                    result["actions_taken"].append("scale_down")
                    result["status"] = "scaled_down"
                    emit_metric("ScalingScaleDown", 1)

                except Exception as e:
                    logger.warning(f"Scale-down failed (non-critical): {e}")
                    result["errors"].append(f"Scale-down: {str(e)}")
                    result["status"] = "completed_with_warnings"
            else:
                result["status"] = "dry_run_scale_down"

        update_lock_status(lock_id, "completed", result)

    except Exception as e:
        logger.error(f"Unexpected error in scaling operation: {e}")
        result["status"] = "failed"
        result["errors"].append(f"Unexpected: {str(e)}")
        update_lock_status(lock_id, "failed", {"error": str(e)})
        emit_metric(
            "ScalingErrors",
            1,
            dimensions=[{"Name": "ErrorType", "Value": "Unexpected"}],
        )

    finally:
        release_lock(lock_id, request_id)

        duration = (datetime.now(timezone.utc) - start_time).total_seconds()
        emit_metric("ScalingExecutionDuration", duration, "Seconds")
        logger.info(
            f"Scaling check completed in {duration:.2f}s with status: {result['status']}"
        )

    status_code = 200 if result["status"] not in ["failed"] else 500
    return {"statusCode": status_code, "body": json.dumps(result, default=str)}


# Local testing support
if __name__ == "__main__":

    class MockContext:
        def __init__(self):
            self.aws_request_id = "local-test-123"
            self.function_name = "blitz-predictive-scaler-local"
            self.memory_limit_in_mb = 512
            self.invoked_function_arn = "arn:aws:lambda:local:123456789:function:local"
            self.remaining_time_in_millis = lambda: 30000

    os.environ["DRY_RUN_MODE"] = "true"

    test_event = {}
    test_context = MockContext()

    response = lambda_handler(test_event, test_context)
    print(f"Response: {json.dumps(response, indent=2)}")
