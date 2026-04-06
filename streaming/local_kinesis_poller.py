#!/usr/bin/env python3
import time
import boto3
import os
import base64
from delta_processor_lambda import lambda_handler

ENDPOINT_URL = os.getenv("ENDPOINT_URL", "http://localhost:4566")
STREAM_NAME = os.getenv("STREAM_NAME", "blitz-data-stream")

client = boto3.client("kinesis", region_name="us-east-1", endpoint_url=ENDPOINT_URL)

def poll_stream():
    print(f"Polling Kinesis stream {STREAM_NAME} at {ENDPOINT_URL}...")
    try:
        # Wait for stream to be active
        while True:
            try:
                response = client.describe_stream(StreamName=STREAM_NAME)
                if response['StreamDescription']['StreamStatus'] == 'ACTIVE':
                    break
            except Exception:
                pass
            time.sleep(1)

        shard_id = response['StreamDescription']['Shards'][0]['ShardId']
        shard_iterator = client.get_shard_iterator(
            StreamName=STREAM_NAME,
            ShardId=shard_id,
            ShardIteratorType='LATEST'
        )['ShardIterator']

        while True:
            response = client.get_records(ShardIterator=shard_iterator, Limit=100)
            records = response.get('Records', [])
            
            if records:
                print(f"Received {len(records)} records. Invoking lambda_handler...")
                
                # Format to match AWS Lambda Kinesis event
                lambda_records = []
                for r in records:
                    lambda_records.append({
                        "kinesis": {
                            "data": base64.b64encode(r['Data']).decode('utf-8')
                        }
                    })
                
                event = {"Records": lambda_records}
                try:
                    result = lambda_handler(event, None)
                    print(f"Lambda Result: {result}")
                except Exception as e:
                    print(f"Lambda Exception: {e}")

            shard_iterator = response['NextShardIterator']
            time.sleep(1)

    except KeyboardInterrupt:
        print("Stopping poller...")
    except Exception as e:
        print(f"Error polling: {e}")

if __name__ == "__main__":
    poll_stream()
