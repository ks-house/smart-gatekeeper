# Orca Task Specification Template

## 1. Task Objective
- **Target Issue**: #<issue_number>
- **Assignee Profile**: <terra | luna>
- **Objective Summary**: <Concise statement of what needs to be implemented/verified>

## 2. Prerequisites & Mandated Reading
- `AGENTS.md` & `.agents/AGENTS.md`
- `wiki/index.md` & recent `wiki/log.md`
- Relevant wiki documents: `<list_wiki_pages>`

## 3. Detailed Scope & Deliverables
1. **Implementation Steps**:
   - `<step_1>`
   - `<step_2>`
2. **Verification Requirements**:
   - `<unit_test_commands>`
   - `<build_commands>`
3. **Documentation Updates**:
   - Update `<wiki_page>`
   - Update `wiki/index.md` if new pages were added
   - Append to `wiki/log.md`

## 4. Invariants & Safety Constraints
- Software Gate `G0-SW` vs Physical Gate `G0-HW` separation
- OTA P0 Non-regression contract
- Feature Flag interlocks
