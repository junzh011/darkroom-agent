# evals

Before/after pairs used to calibrate looks. Put each pair in a folder per shoot:

    evals/<shoot>/<name>_before.<ext>   # straight out of the phone/camera
    evals/<shoot>/<name>_after.jpg      # your own finished edit

`tools/calibrate.py` fits each pair and scores looks against them (see the main README). Videos are skipped by the tool.
Keep a few pairs aside that weren't used to build a look: they're the only fair test of it.

Everything in here except this README is git-ignored, so photos and videos never end up in a public repo by accident.
