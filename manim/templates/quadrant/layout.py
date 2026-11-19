# Layout constants for quadrant template.
# Edit here, then run:  python manim/templates/validate_all.py --template quadrant

QD_AXIS_X     =  0.0   # vertical axis X position
QD_AXIS_Y     =  0.0   # horizontal axis Y position
QD_H_X0       = -6.2   # horizontal axis left X
QD_H_X1       =  6.2   # horizontal axis right X (arrow tip)
QD_V_Y0       = -3.5   # vertical axis bottom Y
QD_V_Y1       =  3.4   # vertical axis top Y (arrow tip)
QD_AXLBL_SZ   = 13     # axis label font size
QD_QH_SZ      = 16     # quadrant header font size
QD_ITEM_SZ    = 13     # item text font size
QD_QH_INSET   =  3.25  # X distance from center to quadrant header center
QD_QH_Y       =  2.8   # Y of quadrant headers (top quadrants)
QD_QH_BY      = -2.8   # Y of quadrant headers (bottom quadrants)
QD_ITEMS_Y0_T =  2.1   # Y of first item in top quadrants
QD_ITEMS_Y0_B = -1.3   # Y of first item in bottom quadrants (-1.5 left the 3rd item touching the header)
QD_ITEM_STEP  = -0.55  # Y step between items (negative = down)
QD_ITEM_MAX_W =  5.5   # max item/header text width before _fit downscales it
QD_AXLBL_FIT_X = 2.2   # max x-axis label width before _fit downscales it
QD_AXLBL_FIT_Y = 1.7   # max y-axis label width (becomes height after rotation)
