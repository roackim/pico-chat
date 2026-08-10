# Profile Form Refactor Plan

## Purpose

Replace the current profile-management implementation with composable controls,
explicit input results, and a state model that owns persistence. The goal is to
remove profile-specific navigation, rendering, and callback mutations from the
form framework and command handler.

## Problems to eliminate

- `ProfileListField` mixes list navigation, selection, rename editing, action
  layout, mouse hit-testing, and profile lifecycle operations.
- `PermissionsCommand` reaches into field internals such as cursor, selection,
  and options state.
- `FormPopup`, `FormContainer`, and fields all partially decide what Enter and
  Space mean.
- `bool` input results cannot distinguish local handling from a request to move
  focus to a sibling.
- Profile actions mutate row counts without a standard container/model update
  path.
- Profile selection, focus, and profile activation are conflated.

## Design principles

1. **Selection is not focus.**
   - Focus determines which control receives the next input.
   - Selection determines the active permission profile.
   - Editing determines which input value is currently being changed.

2. **Containers own sibling navigation.**
   - A child handles local movement first.
   - At a local edge, the child returns a focus intent.
   - Its parent performs the requested sibling move.

3. **Leaves own activation.**
   - Enter, Space, and left mouse click all lead to `activate()` on the actual
     focused/hit-tested leaf control.
   - Parents do not inspect child types to decide action semantics.

4. **Models own mutations and persistence.**
   - UI code calls public model methods.
   - No command or widget writes private cursor/selection state of another
     component.

5. **Layout is derived.**
   - Containers recompute child geometry whenever their child list or preferred
     heights change.
   - Dynamic profile rows must never require manual redraw/offset patches.

## Target architecture

```text
PermissionsForm
  ├── ProfileEditorModel
  │     ├── profile names
  │     ├── selected profile
  │     ├── permission draft
  │     └── create/select/rename/duplicate/remove/save
  │
  └── FormContainer
        ├── ProfileList
        │     ├── ProfileRow
        │     │     ├── RadioItem (select)
        │     │     ├── Button (rename)
        │     │     ├── Button (duplicate)
        │     │     └── Button (remove)
        │     └── Button (create profile)
        ├── HorizontalSelector (permission policy)
        └── Toggle (container settings)
```

## Core input protocol

Introduce an explicit result type, replacing `bool` for new components:

```python
@dataclass(frozen=True)
class InputResult:
    handled: bool = False
    focus: Literal["next", "previous"] | None = None
    redraw: bool = False
```

Rules:

- `handled=True`: stop routing the event.
- `focus="next"` / `"previous"`: parent container moves sibling focus.
- `redraw=True`: owner requests repaint after event handling.
- A parent may translate an unhandled event into its own behavior.
- Existing fields may be adapted through a temporary `bool`-to-`InputResult`
  compatibility adapter during migration.

## Navigation contract

| Input | Owner | Behavior |
|---|---|---|
| Up/Down | focused list/container | Move locally; return focus intent at an edge. |
| Left/Right | focused row/selector | Move among row actions or selector options. |
| Tab/Shift+Tab | nearest form container | Move to next/previous direct form child. |
| Enter/Space | focused leaf | Call `activate()`. |
| Mouse click | hit-tested leaf | Focus leaf, then call the same `activate()`. |
| Escape | modal | Cancel/dismiss only. |

`ProfileList` must not save or load a profile merely because its focus cursor
moves. Selection is changed only by activating the row's select control.

## Model contract

Add `ProfileEditorModel` with public methods only:

```text
profiles() -> list[ProfileSummary]
selected_name -> str
permissions -> ToolPermissionsProfile
select(name) -> None
create() -> ProfileSummary
rename(old_name, new_name) -> ProfileSummary
duplicate(name) -> ProfileSummary
remove(name) -> None
update_permissions(draft) -> None
save() -> None
```

Requirements:

- `create()` persists a complete default profile immediately.
- `update_permissions()` applies and persists the selected profile immediately.
- `rename()` works for built-in/current profiles not yet written to disk by
  saving them under the new name.
- `remove()` chooses a valid remaining selection and applies it, or initializes
  a safe replacement profile if no saved profiles remain.
- Model errors are returned as structured UI-safe errors, not propagated from
  button callbacks.

## Components to add

1. `InputResult` and an adapter for existing `FormField.handle_input()`.
2. `Button` adapter/control with shared keyboard and mouse `activate()`.
3. `HorizontalSelector` with its own selected-option state.
4. `RadioList` with focus cursor distinct from selected item.
5. `ProfileRow`, composed from select/rename/duplicate/remove leaves.
6. `ProfileList`, composed from rows and the create button.
7. `ProfileEditorModel`.
8. `PermissionsForm` builder/controller that binds model changes to controls.

## Migration stages

### Stage 1 — Protect current behavior

- Add regression tests for the currently required behaviors.
- Do not remove `ProfileListField` or alter public component exports yet.
- Verify full test suite before structural edits.

### Stage 2 — Add generic input primitives

- Introduce `InputResult` and container routing support.
- Make `FormContainer` honor focus intents.
- Make `FormPopup` modal-only: Escape, modal action bar, and mouse routing.
- Preserve legacy `bool` field behavior through an adapter.

### Stage 3 — Add model layer

- Implement and unit-test `ProfileEditorModel` independently of the TUI.
- Move create/select/rename/duplicate/remove/save logic out of
  `PermissionsCommand` closures.
- Test persistence, live profile application, validation, and errors.

### Stage 4 — Add composable profile controls

- Implement `Button`, `ProfileRow`, and `ProfileList` against the new input
  protocol.
- Add deterministic layout/hit-test APIs.
- Test keyboard and mouse paths for every action.

### Stage 5 — Rebuild permissions form

- Replace `ProfileListField` usage in `PermissionsCommand` with the new form
  builder/model.
- Bind policy selector and toggle changes to `ProfileEditorModel.update_permissions()`.
- Ensure new/duplicate/remove dynamically rebuild only the profile-list child.

### Stage 6 — Retire legacy behavior safely

- Mark `ProfileListField` deprecated internally after all callers migrate.
- Keep any still-public compatibility export until confirmed unused.
- Delete old code only after all UI, backend, and integration tests pass.

## Required tests

### Model tests

- Selecting loads and applies all profile values.
- Updating one policy immediately applies and persists it.
- Creating immediately persists a complete default profile.
- Duplicate generates a unique name and selects the copy.
- Rename works for saved and initially unsaved active profiles.
- Remove updates selection to a valid profile.
- Invalid/duplicate names return errors without changing state.

### Component tests

- Enter, Space, and click produce the same button action.
- Profile-row Left/Right moves among actions without selecting a profile.
- Profile-list Up/Down moves rows and bubbles at first/last boundaries.
- Tab moves between top-level form controls.
- Mouse hit regions match visible labels.
- Editing a rename field shows a cursor, supports deletion, commit, and cancel.

### Integration tests

- Real `FormPopup`/router event sequence selects, edits, saves, duplicates,
  renames, removes, and creates profiles.
- Dynamic list height moves fields below it without overwritten rows.
- Escape cancels only the active modal and does not leak input to the app.
- Full application suite passes.

## Completion criteria

- No private profile-widget state is modified outside its own component.
- `PermissionsCommand` contains no profile persistence closure logic.
- Popup code has no profile-specific branches.
- Profile lifecycle operations are testable without rendering the TUI.
- Keyboard and mouse activation are identical by contract.
- Selection/focus/editing have separate model state and separate tests.
