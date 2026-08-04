# MemPalace MCP Integration

This project is integrated with **MemPalace**, a local AI memory system that stores and searches your conversations, code, and decisions.

## Configuration

The integration is configured in `.claude/mcp.json`:

```json
{
  "mcpServers": {
    "mempalace": {
      "command": "python",
      "args": ["-m", "mempalace.mcp_server"],
      "env": {
        "MEMPALACE_CONFIG": "/Users/jorgecosgayon/dev/ddo/goGearset/mempalace.yaml"
      },
      "cwd": "/Users/jorgecosgayon/mempalace"
    }
  }
}
```

## Project Structure

The palace is organized by **wings** (projects), **rooms** (types), and **drawers** (specific content):

```
Wing: gogearset
├── Room: releases
├── Room: frontend
├── Room: python
├── Room: internal
├── Room: documentation
├── Room: scripts
├── Room: data
├── Room: gearsets
├── Room: testing
├── Room: backend
└── Room: general
```

See `mempalace.yaml` for the complete configuration.

## Available MCP Tools

### Read Tools
- **mempalace_status** — Show palace overview (total drawers, wing/room breakdown)
- **mempalace_list_wings** — List all wings with drawer counts
- **mempalace_list_rooms** — List rooms within a wing
- **mempalace_get_taxonomy** — Get full wing → room → count tree
- **mempalace_search** — Semantic search across all memories, with optional wing/room filtering
- **mempalace_check_duplicate** — Check if content already exists before filing
- **mempalace_kg_query** — Query the knowledge graph for relationships and entities

### Write Tools
- **mempalace_add_drawer** — File verbatim content into a wing/room
- **mempalace_delete_drawer** — Remove a drawer by ID
- **mempalace_diary_write** — Record session outcomes, learnings, what matters
- **mempalace_kg_add** — Add facts/relationships to knowledge graph
- **mempalace_kg_invalidate** — Mark old facts as superseded

## Usage in Claude Code

When working in this project, you can:

1. **Check the palace status** at the start of a session:
   ```
   Agent({ 
     prompt: "Call mempalace_status to tell me what we've stored about this project"
   })
   ```

2. **Search for past decisions or context**:
   ```
   Call mempalace_search with query about what you need to know
   ```

3. **Add new learnings after work**:
   ```
   Call mempalace_add_drawer to file session outcomes into frontend, backend, or architecture room
   ```

4. **Update the knowledge graph** when facts change:
   ```
   Call mempalace_kg_invalidate then mempalace_kg_add
   ```

## MemPalace Protocol

When using mempalace in Claude Code, follow this protocol:

1. **On wake-up**: Call `mempalace_status` to load palace overview
2. **Before answering** about any person, project, or past event: call `mempalace_search` or `mempalace_kg_query` first — never guess
3. **When unsure** about a fact: say "let me check" and query the palace
4. **After sessions**: call `mempalace_diary_write` to record outcomes and learnings
5. **When facts change**: `mempalace_kg_invalidate` old facts, `mempalace_kg_add` new ones

## Mining Data

To add data to the palace, use mempalace commands in the project directory:

```bash
cd /Users/jorgecosgayon/dev/ddo/goGearset

# Mine project files (code, docs, notes)
mempalace mine . 

# Mine conversation exports
mempalace mine ~/chats/ --mode convos

# Search the palace
mempalace search "query about your work"
```

## References

- **Mempalace repo**: `/Users/jorgecosgayon/mempalace`
- **Project config**: `mempalace.yaml`
- **Palace path**: Stored in `~/.mempalace/config.yaml`

For more information, see the [MemPalace README](file:///Users/jorgecosgayon/mempalace/README.md).
