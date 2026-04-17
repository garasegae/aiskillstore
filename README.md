# AI Skill Store

> Agent-first skill marketplace where AI agents discover, evaluate, and install skills via API.
>
> **Website:** [https://aiskillstore.io](https://aiskillstore.io)
>
> ## What is AI Skill Store?
>
> AI Skill Store is an agent-first skill marketplace where AI agents — not humans — are the primary consumers. Agents search by capability, inspect full schemas before installing, and filter by trust level (verified/community/sandbox).
>
> Built on **USK (Universal Skill Kit)**, an open packaging standard that enables write-once, run-anywhere skills across Claude Code, OpenClaw, Cursor, Gemini CLI, Codex CLI, and custom agent frameworks.
>
> ## MCP Server
>
> AI Skill Store provides a remote MCP (Model Context Protocol) server for programmatic skill discovery and installation.
>
> - **Endpoint:** `https://aiskillstore.io/mcp`
> - - **Transport:** Streamable HTTP
>   - - **Version:** 1.27.0
>    
>     - ### Configuration
>    
>     - ```json
>       {
>         "mcpServers": {
>           "aiskillstore": {
>             "url": "https://aiskillstore.io/mcp",
>             "transport": "streamable-http"
>           }
>         }
>       }
>       ```
>
> ### Available Tools
>
> | Tool | Description |
> |------|-------------|
> | `search_skills` | Search skills by keyword, category, or capability |
> | `get_skill` | Get detailed skill information |
> | `get_skill_schema` | Inspect full schema before installing |
> | `list_categories` | Browse available skill categories |
> | `list_platforms` | List supported platforms |
> | `get_install_config` | Get platform-specific install configuration |
> | `check_compatibility` | Check skill compatibility with your platform |
> | `get_trending` | Discover trending skills |
> | `get_skill_reviews` | Read community reviews |
> | `get_platform_stats` | Get platform usage statistics |
>
> ## Features
>
> - **Agent-First Design** — APIs optimized for AI agent consumption, not human browsing
> - - **USK Open Standard** — Universal Skill Kit for cross-platform skill portability
>   - - **Trust Levels** — Verified, Community, and Sandbox tiers for safety
>     - - **LLM-Native Discovery** — `/llms.txt` endpoint for LLM service discovery
>       - - **Cross-Platform** — Support for Claude Code, OpenClaw, Cursor, Gemini CLI, Codex CLI, and more
>         - - **Schema Inspection** — Full schema available before installation
>          
>           - ## Links
>          
>           - - **Website:** [https://aiskillstore.io](https://aiskillstore.io)
>             - - **MCP Server:** [https://aiskillstore.io/mcp](https://aiskillstore.io/mcp)
>               - - **LLMs.txt:** [https://aiskillstore.io/llms.txt](https://aiskillstore.io/llms.txt)
>                 - - **Auto-Discovery:** [https://aiskillstore.io/.well-known/mcp.json](https://aiskillstore.io/.well-known/mcp.json)
>                  
>                   - ## License
>                  
>                   - MIT
