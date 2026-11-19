from manim.voiceover_prefetch import extract_voiceover_prefetch_plan


def test_extracts_service_config_and_unique_literal_voiceovers():
    source = '''
class Scene_example(VoiceoverScene):
    def construct(self):
        self.set_speech_service(
            LiteLLMTTSService(
                voice="Kore",
                model="manim-speech-synthesis",
                transcription_model=None,
            )
        )
        with self.voiceover(text="First   segment.") as tracker:
            pass
        with self.voiceover(text="Second segment.") as tracker:
            pass
        with self.voiceover(text="First segment.") as tracker:
            pass
'''

    plan = extract_voiceover_prefetch_plan(source)

    assert plan is not None
    assert plan.voice == "Kore"
    assert plan.model == "manim-speech-synthesis"
    assert plan.texts == ("First segment.", "Second segment.")


def test_extracts_voiceovers_assigned_to_constant_names():
    source = '''
class Scene_example(VoiceoverScene):
    def construct(self):
        self.set_speech_service(
            LiteLLMTTSService(voice="Kore", model="manim-speech-synthesis")
        )
        narration_1 = "First variable segment."
        narration_2 = "Second variable segment."
        with self.voiceover(text=narration_1) as tracker:
            pass
        with self.voiceover(text=narration_2) as tracker:
            pass
'''

    plan = extract_voiceover_prefetch_plan(source)

    assert plan is not None
    assert plan.texts == ("First variable segment.", "Second variable segment.")


def test_extracts_voiceovers_from_static_tuple_loop():
    source = '''
class Scene_example(VoiceoverScene):
    def construct(self):
        self.set_speech_service(
            LiteLLMTTSService(voice="Kore", model="manim-speech-synthesis")
        )
        segments = [
            ("S", "First loop segment."),
            ("M", "Second loop segment."),
            ("A", "Third loop segment."),
        ]
        for label, text in segments:
            with self.voiceover(text=text) as tracker:
                pass
'''

    plan = extract_voiceover_prefetch_plan(source)

    assert plan is not None
    assert plan.texts == (
        "First loop segment.",
        "Second loop segment.",
        "Third loop segment.",
    )


def test_extracts_voiceovers_from_static_direct_loop():
    source = '''
class Scene_example(VoiceoverScene):
    def construct(self):
        self.set_speech_service(
            LiteLLMTTSService(voice="Kore", model="manim-speech-synthesis")
        )
        for narration in ["First direct segment.", "Second direct segment."]:
            with self.voiceover(text=narration) as tracker:
                pass
'''

    plan = extract_voiceover_prefetch_plan(source)

    assert plan is not None
    assert plan.texts == ("First direct segment.", "Second direct segment.")


def test_ignores_runtime_computed_voiceover_text():
    source = '''
class Scene_example(VoiceoverScene):
    def construct(self):
        self.set_speech_service(
            LiteLLMTTSService(voice="Kore", model="manim-speech-synthesis")
        )
        narration = build_narration()
        with self.voiceover(text=narration) as tracker:
            pass
'''

    assert extract_voiceover_prefetch_plan(source) is None


def test_skips_prefetch_for_a_single_segment():
    source = '''
class Scene_example(VoiceoverScene):
    def construct(self):
        self.set_speech_service(
            LiteLLMTTSService(voice="Kore", model="manim-speech-synthesis")
        )
        with self.voiceover(text="Only segment.") as tracker:
            pass
'''

    assert extract_voiceover_prefetch_plan(source) is None
