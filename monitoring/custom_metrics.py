"""Custom Metrics Helper for Blitz-Scale Edge Observer.

Provides consistent metric emission across Lambda functions and
helps create CloudWatch dashboards programmatically.
"""

import os
from datetime import datetime, timezone
from typing import Dict, List

import boto3


class MetricsPublisher:
    """Publisher for CloudWatch custom metrics."""

    def __init__(self, namespace: str = 'BlitzScale/Edge', region: str = None):
        self.namespace = namespace
        self.region = region or os.getenv('AWS_REGION', 'us-east-1')
        self.cw = boto3.client('cloudwatch', region_name=self.region)

    def emit(
        self,
        metric_name: str,
        value: float,
        unit: str = 'Count',
        dimensions: Dict[str, str] = None
    ):
        """Emit a single CloudWatch metric.

        Args:
            metric_name: Name of the metric
            value: Metric value
            unit: CloudWatch unit (Count, Seconds, Percent, etc.)
            dimensions: Optional dimension dictionary
        """
        metric_data = {
            'MetricName': metric_name,
            'Value': value,
            'Unit': unit,
            'Timestamp': datetime.now(timezone.utc)
        }

        if dimensions:
            metric_data['Dimensions'] = [
                {'Name': k, 'Value': str(v)}
                for k, v in dimensions.items()
            ]

        try:
            self.cw.put_metric_data(
                Namespace=self.namespace,
                MetricData=[metric_data]
            )
        except Exception as e:
            # Non-fatal: log but don't fail the operation
            import logging
            logging.getLogger('MetricsPublisher').warning(
                f"Failed to emit metric {metric_name}: {e}"
            )

    def emit_latency(self, metric_name: str, latency_ms: float, dimensions: Dict = None):
        """Emit a latency metric in milliseconds."""
        self.emit(metric_name, latency_ms, 'Milliseconds', dimensions)

    def emit_count(self, metric_name: str, count: int = 1, dimensions: Dict = None):
        """Emit a count metric."""
        self.emit(metric_name, float(count), 'Count', dimensions)

    def emit_success_rate(
        self,
        metric_name: str,
        successes: int,
        total: int,
        dimensions: Dict = None
    ):
        """Emit a success rate metric as percentage."""
        rate = (successes / total * 100) if total > 0 else 0
        self.emit(f"{metric_name}SuccessRate", rate, 'Percent', dimensions)


# Pre-configured publishers for different components

class DeltaProcessorMetrics(MetricsPublisher):
    """Metrics specific to the Delta Processor Lambda."""

    def record_delta_computation(self, count: int, latency_ms: float):
        """Record delta computation batch."""
        self.emit_count('DeltasProduced', count)
        self.emit_latency('DeltaComputationLatency', latency_ms)

    def record_edge_push(self, success: bool, latency_ms: float):
        """Record edge push attempt."""
        self.emit_count('EdgePushAttempts')
        if success:
            self.emit_count('EdgePushSuccess')
        else:
            self.emit_count('EdgePushFailure')
        self.emit_latency('EdgePushLatency', latency_ms)

    def record_fantasy_update(self, scoring_format: str, points_delta: float):
        """Record fantasy points update."""
        self.emit(
            f'FantasyPointsDelta_{scoring_format}',
            abs(points_delta),
            'Count',
            {'ScoringFormat': scoring_format}
        )


class EdgeWorkerMetrics(MetricsPublisher):
    """Metrics for Cloudflare Edge Worker (emitted via Cloudflare Workers Analytics)."""

    # Note: Cloudflare Workers uses its own analytics, not CloudWatch
    # This is for when we proxy metrics through a Lambda

    def record_broadcast(self, recipients: int, latency_ms: float):
        """Record a broadcast operation."""
        self.emit_count('WebSocketBroadcasts')
        self.emit_count('ConnectedClients', recipients)
        self.emit_latency('BroadcastLatency', latency_ms)

    def record_connection(self, connected: bool):
        """Record connection/disconnection."""
        metric = 'WebSocketConnections' if connected else 'WebSocketDisconnections'
        self.emit_count(metric)


class PredictiveScalerMetrics(MetricsPublisher):
    """Metrics for the Predictive Scaler Lambda."""

    def __init__(self, region: str = None):
        super().__init__('BlitzScale/PredictiveScaling', region)

    def record_invocation(self, dry_run: bool = False):
        """Record scaler invocation."""
        self.emit_count('ScalingInvocations', 1, {'DryRun': str(dry_run)})

    def record_scale_up(self, games_count: int):
        """Record scale-up operation."""
        self.emit_count('ScalingScaleUp', games_count)

    def record_scale_down(self):
        """Record scale-down operation."""
        self.emit_count('ScalingScaleDown')

    def record_lock_acquired(self):
        """Record successful lock acquisition."""
        self.emit_count('ScalingLockAcquired')

    def record_lock_contention(self):
        """Record lock contention (another instance holding lock)."""
        self.emit_count('ScalingLockContention')

    def record_execution_duration(self, duration_seconds: float):
        """Record total execution duration."""
        self.emit('ScalingExecutionDuration', duration_seconds, 'Seconds')

    def record_error(self, error_type: str):
        """Record an error."""
        self.emit_count('ScalingErrors', 1, {'ErrorType': error_type})


# Dashboard widget generators for CloudWatch

def create_dashboard_body(widgets: List[Dict]) -> Dict:
    """Create a CloudWatch dashboard body.

    Args:
        widgets: List of widget definitions

    Returns:
        Dashboard body dictionary
    """
    return {
        'widgets': widgets
    }


def create_metric_widget(
    title: str,
    metrics: List[List[str]],
    region: str = 'us-east-1',
    period: int = 60,
    width: int = 12,
    height: int = 6
) -> Dict:
    """Create a CloudWatch metric widget.

    Args:
        title: Widget title
        metrics: List of metric definitions [Namespace, MetricName, Dimension1, ...]
        region: AWS region
        period: Aggregation period in seconds
        width: Widget width (1-24)
        height: Widget height (1-1000)

    Returns:
        Widget definition dictionary
    """
    return {
        'type': 'metric',
        'x': 0,
        'y': 0,
        'width': width,
        'height': height,
        'properties': {
            'metrics': metrics,
            'period': period,
            'stat': 'Sum',
            'region': region,
            'title': title,
            'liveData': True
        }
    }


# Example dashboard configuration
DEFAULT_DASHBOARD_WIDGETS = [
    # Latency overview
    create_metric_widget(
        'End-to-End Latency',
        [
            ['BlitzScale/Edge', 'EdgePushLatency', 'Stat', 'p99'],
            ['BlitzScale/Edge', 'DeltaComputationLatency', 'Stat', 'p99'],
        ],
        width=12
    ),

    # Throughput
    create_metric_widget(
        'Delta Processing Rate',
        [
            ['BlitzScale/Edge', 'DeltasProduced'],
        ],
        width=12
    ),

    # Fantasy-specific
    create_metric_widget(
        'Fantasy Updates by Format',
        [
            ['BlitzScale/Edge', 'FantasyPointsDelta_ppr'],
            ['BlitzScale/Edge', 'FantasyPointsDelta_half_ppr'],
            ['BlitzScale/Edge', 'FantasyPointsDelta_standard'],
        ],
        width=12
    ),

    # Scaling operations
    create_metric_widget(
        'Predictive Scaling Activity',
        [
            ['BlitzScale/PredictiveScaling', 'ScalingScaleUp'],
            ['BlitzScale/PredictiveScaling', 'ScalingScaleDown'],
            ['BlitzScale/PredictiveScaling', 'ScalingErrors'],
        ],
        width=12
    ),
]
