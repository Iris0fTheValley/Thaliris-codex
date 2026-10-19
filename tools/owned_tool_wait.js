/* Tool-layer adapter, not a model/agent runtime. No timers, detached promises or
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
