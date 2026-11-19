from learning_pipeline.contracts import LiteralInput, Modality, ModalityProductionPlan, ProductionJob
from learning_pipeline.production import CapabilityCatalog, ProductionCompiler


def test_compiler_maps_capabilities_without_changing_context() -> None:
    production_plan = ModalityProductionPlan(
        plan_id="production-1",
        modality=Modality.VIDEO,
        narrative="Narrated introduction",
        jobs=(
            ProductionJob(
                id="audio",
                capability="narration",
                inputs={"script": LiteralInput(value="Welcome")},
                output_keys=("audio", "timestamps"),
            ),
        ),
        deliverable_job_ids=("audio",),
    )
    compiler = ProductionCompiler(CapabilityCatalog({"narration": "speech.synthesize"}))

    plan = compiler.compile("wf-1", production_plan)

    assert plan.tasks[0].task_type == "speech.synthesize"
    assert plan.tasks[0].inputs["script"].value == "Welcome"
    assert plan.source_plan_id == "production-1"
