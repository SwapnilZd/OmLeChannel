# EHO Podcast Animation

Manim animation for the "In Your Shoes" EHO Podcast episode featuring Kathy Fox.

## Course Generator — Option A (Manim Coordinate Extraction)

Generates a fully interactive e-learning course where interaction hotspots are
placed at **exact pixel coordinates** extracted from the Manim scene graph — not
guessed by the model.

### Pipeline

```
Script
  ↓
[1] legacy-course-video-generation → scene_plan.json
  ↓ (per scene)
[2a] legacy-course-video-generation → Manim code  (ELearningScene: self.elements{} + _export_all())
[2b] Manim render   → frame_<id>.png  +  coords_<id>.json
[2c] legacy-course-video-generation + coords → transparent SVG overlay
[2d] HTML assembly  → Manim PNG (base image) + SVG overlay stacked
  ↓
[3] Index page      → index.html
```

### Usage

```bash
export LITE_LLM_BASE_URL="http://localhost:4000"
export LITE_LLM_API_KEY="sk-..."

# Full pipeline (Manim renders + exact coordinates)
python generate_course.py

# Skip Manim rendering — faster iteration, approximate coords
python generate_course.py --no-render

# Custom script or output directory
python generate_course.py --script my_script.txt --output my_course/

# Provider model selection is managed centrally in ../litellm/config.yaml.
```

### Outputs

```
course_output/
├── index.html                   Landing page with localStorage progress
├── scene_01.html … scene_04.html  Each scene: PNG + transparent SVG overlay + quiz
└── manim_scenes/
    ├── scene_01_<id>.py          Generated Manim scene (ELearningScene subclass)
    ├── coords_<id>.json          Exact pixel positions of each interactive element
    └── frame_<id>.png            Last-frame PNG from Manim render
```

---

## Prerequisites

Requires [Homebrew](https://brew.sh) and Python 3.8+.

### 1. Install system dependencies

```bash
brew install cairo pkg-config pango ffmpeg
```

### 2. Install Python dependencies

**macOS 13–15:**
```bash
pip install -r requirements.txt
```

**macOS 26+ (if pycairo fails to build):**
```bash
PKG_CONFIG_PATH="/opt/homebrew/lib/pkgconfig:/opt/homebrew/Cellar/zlib/1.3.2/lib/pkgconfig:/opt/homebrew/Homebrew/Library/Homebrew/os/mac/pkgconfig/26" \
pip install -r requirements.txt
```

## Rendering

### Interactive (manim-slides) — recommended

```bash
# Step 1 — render (fast preview quality)
manim-slides render -ql podcast_animation.py PodcastAnimation

# Step 2 — present interactively (Space/Right arrow to advance slides)
manim-slides present PodcastAnimation

# Step 3 — export to self-contained HTML (videos embedded, ~1MB)
manim-slides convert --one-file PodcastAnimation output.html

# Step 3 — export to PowerPoint
manim-slides convert PodcastAnimation output.pptx
```

The HTML output is fully self-contained and embeddable in any LMS.
There are 15 pause points (slides) across 9 sections.

### Plain video (no interactivity)

```bash
# Fast preview (480p)
manim -pql podcast_animation.py PodcastAnimation

# High quality (1080p)
manim -pqh podcast_animation.py PodcastAnimation
```

Output is saved to `media/videos/podcast_animation/`.
