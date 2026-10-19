const assert = require("node:assert/strict");
const {waitOwnedCommand} = require("../tools/owned_tool_wait.js");

(async () => {
  let calls = 0;
  const tools = {
    exec_command: async () => ({session_id: 17, output: "ordinary progress"}),
    write_stdin: async (args) => {
      assert.equal(args.session_id, 17);
      assert.equal(args.chars, "");
      return ++calls < 3 ? {session_id: 17, output: ""} : {exit_code: 7, output: "failed"};
    }
  };
  const result = await waitOwnedCommand(tools, {}, {maxBufferedChars: 6});
  assert.equal((await waitOwnedCommand(tools, {}, {maxBufferedChars: 0})).status, "UNKNOWN");
  assert.equal(result.status, "TERMINAL");
  assert.equal(result.exit_code, 7);
  assert.equal(result.observations, 4);
  assert.equal(result.truncated, true);
  assert.equal(result.semantic_done, false);
  assert.equal((await waitOwnedCommand({exec_command: async () => ({})}, {})).status, "UNKNOWN");
  const initialError = await waitOwnedCommand({exec_command: async () => ({session_id: 23, isError: true,
    output: "session established before tool error"})}, {});
  assert.equal(initialError.status, "UNKNOWN");
  assert.equal(initialError.session_id, 23);
  assert.match(initialError.reason, /Tool observation error/);
  assert.equal((await waitOwnedCommand({...tools, write_stdin: async () => ({session_id: 18})}, {})).status, "UNKNOWN");
  const changedError = await waitOwnedCommand({...tools, write_stdin: async () => ({session_id: 18, isError: true})}, {});
  assert.equal(changedError.status, "UNKNOWN");
  assert.equal(changedError.session_id, 17);
  assert.match(changedError.reason, /Owned session changed/);
  assert.equal((await waitOwnedCommand({...tools, write_stdin: async () => {throw Error("Host boundary");}}, {})).status, "UNKNOWN");
  assert.equal((await waitOwnedCommand({...tools, write_stdin: async () => ({session_id: 17, status: "NOT_FOUND"})}, {})).status, "UNKNOWN");
  const cancelled = await waitOwnedCommand(tools, {}, {signal: {aborted: true}});
  assert.equal(cancelled.status, "INTERVENTION_REQUIRED");
  assert.equal(cancelled.session_id, 17);
  assert.equal((await waitOwnedCommand({...tools, exec_command: async () => ({exit_code: 0})}, {})).status, "TERMINAL");
  const callbackFailure = await waitOwnedCommand({exec_command: async () => ({exit_code: 0, output: "done"})}, {},
    {onProgress: () => {throw Error("display failed");}});
  assert.equal(callbackFailure.status, "TERMINAL");
  assert.match(callbackFailure.progress_error, /display failed/);
  process.stdout.write("owned tool wait: PASS\n");
})().catch(error => {process.stderr.write(String(error)); process.exitCode = 1;});
