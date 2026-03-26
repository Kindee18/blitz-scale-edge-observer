import base64
import gzip
import json
import logging
import os
import boto3
from datetime import datetime

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# For actual deployment we'd configure the bucket name
S3_BUCKET = os.getenv('LOG_BUCKET_NAME', 'blitz-edge-aggregated-logs')
s3_client = boto3.client('s3')

def process_log_events(log_events):
    """
    Filters incoming log events.
    Drops duplicate or heartbeat logs.
    Retains only errors and critical gameplay events.
    """
    filtered_logs = []
    dropped_count = 0

    for event in log_events:
        message = event.get('message', '').strip()
        
        # Drop logic
        if 'heartbeat' in message.lower() or 'debug' in message.lower():
            dropped_count += 1
            continue
            
        # Retention logic
        if 'error' in message.lower() or 'critical' in message.lower() or 'gameplay_event' in message.lower():
            filtered_logs.append(event)
        else:
            # Default drop for extreme savings, or we could sample
            dropped_count += 1
            
    return filtered_logs, dropped_count

def lambda_handler(event, context):
    """
    Entry point for CloudWatch Logs triggering Lambda.
    CloudWatch Log data is base64 encoded and gzipped.
    """
    # CloudWatch Logs structure: {'awslogs': {'data': 'base64+gzipped payload'}}
    if 'awslogs' not in event:
        return {'statusCode': 400, 'body': 'Not a CloudWatch Log event'}
        
    encoded_data = event['awslogs']['data']
    compressed_data = base64.b64decode(encoded_data)
    uncompressed_data = gzip.decompress(compressed_data)
    
    log_data = json.loads(uncompressed_data)
    log_events = log_data.get('logEvents', [])
    log_group = log_data.get('logGroup', 'unknown-group')
    
    filtered_logs, dropped_count = process_log_events(log_events)
    
    logger.info(f"Processed {len(log_events)} events from {log_group}. Dropped: {dropped_count}, Retained: {len(filtered_logs)}")
    
    if filtered_logs:
        # Batch and write retained logs to S3
        timestamp = datetime.utcnow().strftime('%Y/%m/%d/%H-%M-%S')
        object_key = f"filtered-logs/{log_group.replace('/', '-')}/{timestamp}-{context.aws_request_id}.json"
        
        payload = '\n'.join([json.dumps(l) for l in filtered_logs])
        
        try:
            s3_client.put_object(
                Bucket=S3_BUCKET,
                Key=object_key,
                Body=payload.encode('utf-8')
            )
            logger.info(f"Successfully wrote {len(filtered_logs)} logs to s3://{S3_BUCKET}/{object_key}")
        except Exception as e:
            logger.error(f"Failed to write logs to S3: {e}")
            raise e

    # In a real pipeline, we might return the filtered logs back or just succeed to acknowledge.
    return {'statusCode': 200, 'body': 'Processing complete'}
