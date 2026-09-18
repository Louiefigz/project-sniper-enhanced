# A local HTTP test must identify the server before writing

A successful response from `127.0.0.1` proves that a server answered. It does
not prove that the test started that server. During the supporting-media test
review, the first prepared harness accepted a generic ingest HTTP 400 as its
readiness signal. If the chosen port was already occupied, the next request
could create a project in a different running app's workspace. That harness
was rejected before any server or media launched.

The passing harness adds a clearly test-only identity endpoint to its disposable
app copy. Its frozen response includes a unique run nonce plus actual process
ID, working directory and workspace. Before each mutation, the client verifies
those values and checks that the responding PID belongs to the process group
the owner created. The identity response and mutation use one HTTP connection;
the client rejects closing responses and disables automatic reconnection.

```python
connection = verified_connection(runtime, owned_server_group, timeout)
# verified_connection checks the identity and sets auto_open = 0.
connection.request('POST', '/api/producer/ingest', body, headers)
response = connection.getresponse()
```

The same-connection rule matters. A separate identity check followed by a new
connection leaves a race if the owned server exits and another app binds its
port. A failed verified connection must fail the request, not silently reconnect.

Four real HTTP/SSE tests passed in 11.120 seconds. The server became ready in
2.506 seconds; all seven actual Python ingest children were observed through
exit. The complete owner and exact cleanup took 49.854 seconds. The test-only
route exists only in the isolated artifact copy and was never added to production.
See [the integration receipt](../producer/SUPPORTING_MEDIA_AND_GUIDED_BUILD_2026-09-13.md).

This is an acceptance-harness ownership check, not application authentication.
Do not ship a debugging identity endpoint or use a run nonce as a replacement
for the production app's local-origin policy, mutation leases or media admission.
