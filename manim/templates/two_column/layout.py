# Layout constants for two_column.
# Edit here, then run:  python manim/templates/validate_all.py --template two_column

TC_COL_X       =  3.5   # column center X offset (±) from divider
TC_HEADER_Y    =  2.8   # header row Y position
TC_CARD_W      =  5.5   # row card width (same across all tiers)
TC_CARD_RADIUS =  0.15  # row card corner radius
TC_HEADER_SZ   = 30     # header font size

# Auto-scaling tiers by item count: (body_sz, card_h, row_step, row_y0)
# Edit per-tier values here to tune each density independently.
# body_sz must keep a 32-char item inside the 5.5 card (font 30 measured 6.55).
TC_TIERS: dict = {
    3: (22, 0.85, -1.50, 1.6),
    4: (24, 0.70, -1.20, 1.7),
    5: (20, 0.60, -1.00, 1.8),
    6: (16, 0.50, -0.88, 1.9),
}
