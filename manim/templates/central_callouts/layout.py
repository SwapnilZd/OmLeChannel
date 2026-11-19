# Layout constants for central_callouts.
# Edit here, then run:  python manim/templates/validate_all.py --template central_callouts

CC_HUB_R     =  0.9   # hub circle radius
CC_HUB_FIT   =  1.7   # max hub label width (chord inside the hub — label is white on white outside it)
CC_DOT_R     =  0.2   # callout dot radius
CC_ARROW_B   =  0.22  # arrow tip clearance (buff)
CC_CENTER_SZ = 19     # hub label font size
CC_LBL_BUFF  =  0.15  # callout label offset from dot
CC_LBL_FIT   =  3.0   # max callout label width before _fit downscales it

# Auto-scaling tiers by callout count: (callout_sz, spoke_r)
# spoke_r grows slightly at higher counts to give labels more breathing room.
CC_TIERS: dict = {
    3: (22, 2.8),
    4: (20, 3.0),
    5: (18, 3.1),
    6: (16, 3.2),
    7: (14, 3.2),
    8: (13, 3.3),
}
