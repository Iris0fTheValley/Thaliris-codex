"""Deliver a packaged tool helper through the pinned console, without activation.

Retrieval is read-only. Selection flags describe an already authorized operation;
they do not authenticate an actor or grant execution or cancellation authority.
"""
from hashlib import sha256


# Canonical JS is pinned with this Python module. The repo JS is generated.
TOOL_SOURCE = r'''/* Tool-layer adapter, not a model/agent runtime. No timers, detached promises or
 * collaboration tools. Embed this function in functions.exec's JS isolate. */
async function waitOwnedCommand(tools, args, options = {}) {
  const {onProgress, maxBufferedChars = 16384, signal} = options;
  let session;
  let output = "";
  let truncated = false;
  let observations = 0;
  let progressError;
  const append = (chunk = "") => {
    output += chunk;
    if (output.length > maxBufferedChars) {
      output = output.slice(-maxBufferedChars);
      truncated = true;
    }
  };
  try {
    if (!Number.isSafeInteger(maxBufferedChars) || maxBufferedChars < 1)
      throw new Error("Positive bounded output size required");
    if (signal?.aborted)
      return {status: "INTERVENTION_REQUIRED", reason: "cancelled before launch",
        observations: 0, semantic_done: false};
    let result = await tools.exec_command(args);
    if (Number.isInteger(result.session_id)) session = result.session_id;
    while (true) {
      observations++;
      if (session !== undefined && result.session_id !== undefined && result.session_id !== session)
        throw new Error("Owned session changed");
      append(result.output);
      if (result.isError || result.error || ["UNKNOWN", "ERROR", "NOT_FOUND"].includes(result.status))
        throw new Error("Tool observation error: " + String(result.error ?? result.status));
      if (onProgress && result.output) {
        try { await onProgress(result.output); }
        catch (error) { progressError = String(error); }
      }
      if (result.exit_code !== undefined && result.exit_code !== null) {
        if (!Number.isInteger(result.exit_code)) throw new Error("Invalid terminal exit code");
        return {status: "TERMINAL", exit_code: result.exit_code, output,
          truncated, observations, progress_error: progressError, semantic_done: false};
      }
      if (!Number.isInteger(result.session_id)) throw new Error("Missing owned session; liveness UNKNOWN");
      if (session !== undefined && result.session_id !== session) throw new Error("Owned session changed");
      session = result.session_id;
      if (signal?.aborted || progressError) {
        // No guessed PID, thread resume, new command or process-wide kill.
        return {status: "INTERVENTION_REQUIRED", reason: progressError ?? "cancellation requested",
          session_id: session, output, truncated, observations, semantic_done: false,
          recovery: "use the operation's exact durable cancellation request; reconcile original tool session"};
      }
      result = await tools.write_stdin({session_id: session, chars: "",
        yield_time_ms: 300000, max_output_tokens: args.max_output_tokens ?? 1000});
    }
  } catch (error) {
    return {status: "UNKNOWN", reason: String(error), session_id: session,
      output, truncated, observations, semantic_done: false,
      recovery: "inspect durable receipt; reconcile original tool session manually"};
  }
}
// Selection is operational metadata, never task/actor authority. Only a fresh
// exec result establishes this helper's session; there is no attach-by-ID API.
async function observeOwnedCommand(tools, args, options = {}) {
  const selected = options.expectedLong === true && options.finite === true &&
    options.noninteractive === true && args.tty !== true &&
    typeof tools.write_stdin === "function";
  if (!selected) {
    // Preserve native interaction and permissions. Never retry an uncertain start.
    return {mode: "NATIVE", observation: await tools.exec_command(args), semantic_done: false};
  }
  return {mode: "OWNED_WAIT", ...await waitOwnedCommand(tools, args, options)};
}
if (typeof module !== "undefined") module.exports = {waitOwnedCommand, observeOwnedCommand};
'''


INSTRUCTIONS = (
    "For your own expected-long, finite, noninteractive command or CI observation, "
    "invoke `<installed pinned runner> execution-wait --tool-source`. This command supplies the "
    "packaged tool helper and exact usage; keep observation in one functions.exec "
    "call. Short, interactive, unsupported or unowned operations use their native "
    "tool; missing capability must not block authorized work. A running outer cell "
    "is a Host boundary: continue only its exact cell with functions.wait, requesting "
    "a supported long yield when no decision is pending. Do not relaunch its command "
    "or equate progress, timeout or tool termination with completion. Runtime "
    "interruption and automatic recovery remain UNKNOWN without direct evidence. "
)


def guide(*, include_source: bool = False) -> dict:
    source = TOOL_SOURCE
    result = {
        "ok": True,
        "authority": "NONE; existing role, task, permissions and sandbox still apply",
        "selection": "expected long + finite + noninteractive + this call starts and owns the session",
        "fallback": "Use the native tool for short/interactive/unowned work or unavailable helper; never relaunch after an uncertain start.",
        "usage": [
            "In functions.exec, request a supported long outer yield via its first-line pragma.",
            "Read JSON from `<installed pinned runner> execution-wait --tool-source` using tools.exec_command. Require exit_code 0 and ok true before loading source. An old runner may reject this command; use the native tool then.",
            "const observeOwnedCommand = new Function(packet.source + '; return observeOwnedCommand;')();",
            "text(await observeOwnedCommand(tools, authorizedExecArgs, {expectedLong:true, finite:true, noninteractive:true}));",
            "If the Host yields a running cell, functions.wait only that exact cell; explicitly request a supported long yield. No automatic Desktop continuation is claimed.",
            "For durable process/CI output and exact correlation: execution-wait run|github|inspect|cancel with the existing --identity/--receipt options; execution-wait run --help describes them. Wrap this foreground CLI observation with the same helper.",
        ],
        "limits": {
            "output": "bounded tail; not a durable output archive",
            "cancellation": "stopping the JS cell does not prove external termination; use original native session or exact durable cancel and verify outcome",
            "native_children": "wait_agent only for necessary unfinished direct native dependencies; not wrapped here",
            "host_activation": "UNKNOWN; source retrieval proves no profile reload",
            "semantic_done": False,
        },
        "source_sha256": sha256(source.encode()).hexdigest(),
    }
    if include_source:
        result["source"] = source
    return result
