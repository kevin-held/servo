# lx_steps.py
#
# Phase E (UPGRADE_PLAN_4 sec 6) -- step-name registry consumed by the
# GUI loop panel and any other widget that needs the canonical phase
# labels without importing the cognate runtime.
#
# Phase G (UPGRADE_PLAN_6 sec 1, D-20260427-01) -- the No-Write
# invariant on `core/loop.py` was lifted and the file deleted, so the
# previous `from core.loop import LoopStep as _LoopStep` re-export had
# nowhere to land. The enum values are now defined directly in this
# file, which is now the canonical home for the phase-name vocabulary.
#
# The values still spell the historical six-step manifest order
# (PERCEIVE, CONTEXTUALIZE, REASON, ACT, INTEGRATE, OBSERVE) so the
# loop_panel STEP_ORDER list and the gui color-map keyed on these
# names continue to render legacy traces correctly. Phase G Step 2
# will introduce a four-step display vocabulary in `gui/loop_panel.py`
# itself; the four cognate phases (OBSERVE, REASON, ACT, INTEGRATE)
# are listed below in their cognate-loop order as well, so consumers
# can pick whichever vocabulary fits.


class LoopStep:
    # Historical six-step manifest -- preserved for legacy log replay
    # and tests that reference these names by attribute.
    PERCEIVE       = "PERCEIVE"
    CONTEXTUALIZE  = "CONTEXTUALIZE"
    REASON         = "REASON"
    ACT            = "ACT"
    INTEGRATE      = "INTEGRATE"
    OBSERVE        = "OBSERVE"


# Public alias. Consumers should import either name; both refer to the
# same class object so identity checks (Step.PERCEIVE is LoopStep.PERCEIVE)
# stay True.
Step = LoopStep


__all__ = ["Step", "LoopStep"]
