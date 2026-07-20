# LazyAgent Demo Script

Use this as the shot list for a 60-second GIF or short video.

## Goal

Show that LazyAgent is not just another agent wrapper. It is a local control plane that gives multiple coding agents shared runtime policy, memory, and review gates.

## 60-Second Flow

1. Open the repository README and show the LazyAgent banner.
2. Open a terminal in the repo.
3. Show current profile:

   ```powershell
   harness-toggle.bat status
   ```

4. Switch to a low-cost profile:

   ```powershell
   harness-toggle.bat standard
   ```

5. Show the profile again:

   ```powershell
   harness-toggle.bat status
   ```

6. Run a static-safe check:

   ```powershell
   python smoke_test.py
   ```

7. Show one MCP/control-plane feature in the README:

   - runtime profiles
   - lesson memory
   - panel review
   - setup automation for Claude/Codex/Gemini

8. End on the repo URL:

   ```text
   https://github.com/hung1597865420/LazyAgent
   ```

## Recording Notes

- Do not show `.env`, API keys, local user paths, cost reports, or private endpoints.
- Keep the terminal zoomed enough for commands to be readable.
- Prefer a 1280x720 crop.
- Keep the first version simple; clarity beats cinematic editing.

## Short Voiceover

> LazyAgent is an MCP control plane for coding agents. It gives Claude Code, Codex, Gemini/Antigravity, and compatible clients shared runtime profiles, lesson memory, review gates, and setup automation. Start safe with profile off, opt in when you need heavier automation, and keep agents from silently burning quota.
