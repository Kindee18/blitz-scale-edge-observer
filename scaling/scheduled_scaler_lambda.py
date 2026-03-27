import json
import logging
import os
import boto3
from datetime import datetime, timezone

# We import the core logic
# In a real packaging, these would be in the same layer or package
from predictive_scaling import is_spike_imminent, trigger_karpenter_scale_up, trigger_karpenter_scale_down, get_kube_config

logger = logging.getLogger()
logger.setLevel(logging.INFO)

SCHEDULE_S3_BUCKET = os.getenv('SCHEDULE_S3_BUCKET')
SCHEDULE_S3_KEY = os.getenv('SCHEDULE_S3_KEY', 'game_schedules/nfl_today.json')

def lambda_handler(event, context):
    """
    Lambda entry point for scheduled scaling checks.
    Triggered by EventBridge every 15 minutes.
    """
    logger.info("Starting scheduled scaling check...")
    
    # Load schedule from S3 instead of local file
    s3 = boto3.client('s3')
    try:
        response = s3.get_object(Bucket=SCHEDULE_S3_BUCKET, Key=SCHEDULE_S3_KEY)
        schedule = json.loads(response['Body'].read().decode('utf-8'))
    except Exception as e:
        logger.error(f"Error loading schedule from S3: {e}")
        return {'statusCode': 500, 'error': str(e)}

    apps_v1, core_v1 = get_kube_config()
    
    if is_spike_imminent(schedule, lead_time_minutes=45): # Slightly longer lead for automation
        logger.info("Kickoff spike imminent. Scaling up cluster pool...")
        trigger_karpenter_scale_up(apps_v1, core_v1)
        action = "scaled_up"
    else:
        logger.info("No spikes detected. Ensuring cluster is at base scale.")
        trigger_karpenter_scale_down(apps_v1)
        action = "scaled_down"

    return {
        'statusCode': 200,
        'body': json.dumps({
            "action": action,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
    }
