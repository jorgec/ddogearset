# Gemini → Claude Agent & Skill Adaptation

This document describes the adaptation of `.gemini` agents and skills for Claude Code.

## Structure Mapping

### Gemini → Claude
- `.gemini/agents/` → `.claude/agents/`
- `.gemini/skills/` → `.claude/skills/`

## Agent Adaptations

All 7 agents have been adapted with the following changes:

### Format Changes
- Removed `inheritMcp: true` (Claude agents inherit tool access by default)
- Removed `hidden: true` 
- Updated to Claude's YAML frontmatter format
- Added `model: opus` (appropriate for complex reasoning tasks)
- Added `reasoning_effort: high` for strategic planning agents (orchestrator, spec_builder, verifier)

### Tool Access Mapping
Gemini agents used a hardcoded tools list. Claude agents don't specify tools in the config—they have access to all available tools based on permission mode. The system automatically grants appropriate access.

**Equivalent tools in Claude:**
| Gemini | Claude | Notes |
|--------|--------|-------|
| send_message | SendMessage | Available via deferred tools |
| find_by_name | Bash (grep/find) | Use Read + grep |
| grep_search | Bash | `grep -r` via Bash |
| view_file | Read | Built-in file reader |
| list_dir | Bash | `ls` via Bash |
| read_url_content | WebFetch | Deferred tool |
| search_web | WebSearch | Deferred tool |
| schedule | CronCreate / schedule skill | Deferred tool or skill |
| generate_image | N/A | No equivalent in Claude |
| multi_replace_file_content | Edit | Built-in editor |
| replace_file_content | Edit | Built-in editor |
| write_to_file | Write | Built-in writer |
| run_command | Bash | Built-in bash execution |
| manage_task | TaskCreate/TaskUpdate | Deferred tools |
| notebook_edit | NotebookEdit | Deferred tool |
| define_subagent/invoke_subagent | Agent tool + subagent_type | Subagents created via prompt |

### Agent Descriptions

1. **orchestrator** - CTO/Senior Engineer role for architectural decisions and planning
2. **spec_builder** - Creates technical specifications before implementation
3. **builder** - Implements code according to specs and plans
4. **test_builder** - Creates tests for critical components
5. **tester** - Runs test suites and reports results
6. **verifier** - Verifies test accuracy and checks for false positives
7. **project_manager** - Manages user stories, execution order, git commits

## Skill Adaptations

### frontend_tester
Focuses on preventing common Svelte/Wails frontend gotchas:
- Import path resolution
- Path aliases configuration
- Build tool compatibility (Vite, Rollup, Wails)
- Wails binding verification

## Usage

To use these agents with Claude Code, you can:

1. **Name an agent explicitly when spawning:**
   ```bash
   claude --agent orchestrator
   ```

2. **Or spawn subagents in conversation:**
   ```
   Agent({
     description: "Planning feature X",
     subagent_type: "orchestrator",
     prompt: "..."
   })
   ```

3. **Use skills in conversation:**
   ```
   /frontend_tester
   ```

## Key Differences from Gemini Setup

1. **No tool list in agent config** - Claude manages tool access through permission mode
2. **No MCP inheritance flag** - Claude agents automatically have MCP access
3. **Simpler frontmatter** - Just name, description, model, and reasoning_effort
4. **Skill invocation** - Skills are triggered via `/skillname` or called with `Skill()` tool
5. **Subagents** - Created dynamically via `Agent()` tool with `subagent_type` parameter

## Deployment Notes

- The `.claude` directory is read by Claude Code automatically
- No build step required - agents and skills are available immediately
- Update agent descriptions and instructions in the YAML frontmatter as needed
- Test agents in isolated sessions before using in critical workflows
