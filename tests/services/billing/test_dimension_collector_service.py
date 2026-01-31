from src.models.database import DimensionCollector
from src.services.billing.dimension_collector_service import (
    DimensionCollectInput,
    DimensionCollectorRuntime,
)


class TestDimensionCollectorRuntime:
    def test_priority_fallback(self) -> None:
        runtime = DimensionCollectorRuntime()
        collectors = [
            DimensionCollector(
                api_format="OPENAI",
                task_type="chat",
                dimension_name="input_tokens",
                source_type="response",
                source_path="usage.prompt_tokens",
                value_type="int",
                priority=10,
                is_enabled=True,
            ),
            DimensionCollector(
                api_format="OPENAI",
                task_type="chat",
                dimension_name="input_tokens",
                source_type="response",
                source_path="usageMetadata.promptTokenCount",
                value_type="int",
                priority=5,
                is_enabled=True,
            ),
        ]
        dims = runtime.collect(
            collectors=collectors,
            inp=DimensionCollectInput(
                response={"usageMetadata": {"promptTokenCount": 123}},
            ),
        )
        assert dims["input_tokens"] == 123

    def test_transform_expression_value(self) -> None:
        runtime = DimensionCollectorRuntime()
        collectors = [
            DimensionCollector(
                api_format="GEMINI",
                task_type="video",
                dimension_name="file_size_mb",
                source_type="metadata",
                source_path="result.file_size_bytes",
                transform_expression="value / 1024 / 1024",
                value_type="float",
                priority=0,
                is_enabled=True,
            )
        ]
        dims = runtime.collect(
            collectors=collectors,
            inp=DimensionCollectInput(metadata={"result": {"file_size_bytes": 1048576}}),
        )
        assert abs(dims["file_size_mb"] - 1.0) < 1e-9

    def test_computed_dimension(self) -> None:
        runtime = DimensionCollectorRuntime()
        collectors = [
            DimensionCollector(
                api_format="CLAUDE",
                task_type="chat",
                dimension_name="input_tokens",
                source_type="request",
                source_path="usage.input_tokens",
                value_type="int",
                priority=0,
                is_enabled=True,
            ),
            DimensionCollector(
                api_format="CLAUDE",
                task_type="chat",
                dimension_name="cache_read_tokens",
                source_type="request",
                source_path="usage.cache_read_tokens",
                value_type="int",
                priority=0,
                is_enabled=True,
            ),
            DimensionCollector(
                api_format="CLAUDE",
                task_type="chat",
                dimension_name="total_input_tokens",
                source_type="computed",
                source_path=None,
                transform_expression="input_tokens + cache_read_tokens",
                value_type="int",
                priority=0,
                is_enabled=True,
            ),
        ]
        dims = runtime.collect(
            collectors=collectors,
            inp=DimensionCollectInput(
                request={"usage": {"input_tokens": 100, "cache_read_tokens": 20}}
            ),
        )
        assert dims["input_tokens"] == 100
        assert dims["cache_read_tokens"] == 20
        assert dims["total_input_tokens"] == 120
