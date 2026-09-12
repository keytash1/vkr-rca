# M13 Trace Contract

The Jaeger adapter emits only trace/span IDs for reconstruction, parent ID,
service join key, peer join key, timestamps, duration, generic span kind, error
flag and observed service edge. Operation names, routes, service embeddings,
system identity, dataset identity, fault identity and root labels are forbidden
features. Exclusive duration subtracts the exact union of overlapping local
client-descendant waits. `traces_collected` is distinct from an expected service
or edge disappearing from a successfully collected window.
