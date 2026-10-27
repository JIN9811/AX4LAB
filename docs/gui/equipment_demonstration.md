# Create an Equipment Skill from a demonstration

The human demonstrates the procedure; the selected vision-capable Local/API model interprets the recording afterward. It does not compete with the operator for mouse control. Normal execution uses the reviewed, compiled Skill rather than asking the model to choose every click.

## Record and interpret

1. In **Windows Automation**, select the instrument profile and its paired Worker.
2. Record the procedure in the Windows bridge console. Capture targets **15 FPS**. Screen acquisition and encoding/storage are separate; timestamped keyboard/mouse events and their before/after images are retained alongside the full timeline.
3. Stop and save the recording. Finalization waits for pending writes. Check `evidence_complete`: disk errors, dropped evidence or capture failures must not be mistaken for a complete demonstration.
4. Select the saved recording and choose **Import Selected & Build Draft**. The selected vision-capable endpoint analyzes event/transition frames and creates an editable Skill.
5. Open the workflow editor. Expand each step to review its intent, target, preconditions, expected outcome and success/failure evidence. Correct uncertain interpretations before saving the review.

The VLM sees at most 128 selected frames per recording, not every frame of the 15 FPS stream. Full original files remain available. Missing action coverage is disclosed and requires review; long demonstrations may be easier to review as separate Skills.

## Review before deployment

- The recorded actions remain authoritative. A model cannot silently replace them.
- Proposed variables are suggestions, not automatic substitutions into commands.
- Proposed image locators require separate explicit approval. Approving only the description does not apply a target change.
- Use **Reject Locator & Save Review** to keep the recorded or manually corrected target instead of accepting a model proposal.
- Applying a locator invalidates old compiled programs. Annotation changes also invalidate previous validation/deployment: compile when needed, validate, test in the intended environment, then deploy again.
- A completed authoring job can still require review. **Review required** does not mean ready for execution.

## Visual error restoration

For a GUI failure proven to occur before the failed segment performed any action, the Equipment agent can examine a fresh screenshot and choose a bounded restoration: focus the configured window, wait briefly, or dismiss a non-operating transient dialog with one Escape.

After restoration it captures another screen and checks readiness before retrying the unexecuted segment/block. Completed steps are not replayed. Unknown action effects, missing/corrupted screen evidence, an unresolved dialog, or an active stop request require operator attention. This is GUI restoration, not permission to acknowledge arbitrary warnings or repeat a physical test.

Recovery decisions, before/after evidence and verification results stay in the execution record. They are candidates for later review, not automatically promoted changes to the deployed Skill. Existing end-of-workflow measurement and handoff checks still apply.

## Deployment and limits

The Windows host needs the updated bridge source/package; Linux-only changes do not update a running Windows Worker. Both the Linux authoring/runtime process and the Windows recorder must load the new code before these behaviors are active.

Recording uses JPEG/PNG evidence, not an MP4 codec. Disk use depends on screen content and duration. The 15 FPS target is not a native-Windows performance guarantee. Use a short supervised demonstration to confirm capture rate and evidence completeness on the actual Windows host before recording a long procedure.
