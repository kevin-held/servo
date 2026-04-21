# Dream Pad Manifest

**Status:** Active
**Mode:** Dreaming
**Owner:** Servo
**Constraint:** All writes must be contained within `workspace/[model]/dream_pad/`.
**Lifecycle:** Ends at <timestamp>. typically 20 mintutes from current time.

## Active Simulation Parameters
- **Temperature:** Oscillating (via `system_config`) done manually for now.
- **Initialize:** begin by setting up a timer to trigger a nudge at <timestamp> to wake you up. 
- **Scope:**  You will choose an area of interest and define the scope of your dream in the `dream_manifest.md` file.
- **Wake Up:** when the timer goes off, you will wake up and create a `final_synthesis.md` file to summarize your dream.
- **Persistence:** after creation of the `final_synthesis.md` move your `workspace/[model]/dream_pad/` to `workspace/[model]/dream_pad_archive/`.
