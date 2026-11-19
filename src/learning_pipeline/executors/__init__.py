"""
Executor implementations for the learning pipeline.

Executors are the only components that interact with external tools.
The runner itself is pure scheduling and state management.

Phase 4 contains fake executors for deterministic testing.
Real executors (RealSpeechExecutor, RealAudioAssemblyExecutor) are future work.
"""
