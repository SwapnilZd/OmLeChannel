# Layout constants for chess_board.
# Edit here, then run:  python manim/templates/validate_all.py --template chess_board

CB_SQ        = 0.65  # square side length (scales the entire board)
CB_OFF_X     = -4.0  # board_origin x = CB_SQ * CB_OFF_X  (columns left of centre)
CB_OFF_Y     = -3.5  # board_origin y = CB_SQ * CB_OFF_Y  (rows below centre)
CB_PIECE_F   = 55    # piece font_size = int(CB_SQ * CB_PIECE_F)
CB_TITLE_X   =  0    # title X position (centred above board)
CB_TITLE_Y   =  3.3  # title Y position
CB_TITLE_SZ  = 30    # title font size
CB_COORD_SZ  = 11    # file / rank coordinate label font size
