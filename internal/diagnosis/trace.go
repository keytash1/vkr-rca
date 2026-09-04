package diagnosis

import (
	"sort"
	"time"
)

type interval struct {
	start time.Time
	end   time.Time
}

func ExclusiveObserved(spans []TraceSpan, serverSpanID string) (TraceMeasurement, bool) {
	byID := make(map[string]TraceSpan, len(spans))
	children := make(map[string][]string)
	for _, span := range spans {
		byID[span.SpanID] = span
		if span.ParentSpanID != "" {
			children[span.ParentSpanID] = append(children[span.ParentSpanID], span.SpanID)
		}
	}
	server, exists := byID[serverSpanID]
	if !exists || server.Kind != SpanKindServer || !server.EndTime.After(server.StartTime) {
		return TraceMeasurement{}, false
	}

	visited := map[string]struct{}{server.SpanID: {}}
	queue := append([]string(nil), children[server.SpanID]...)
	intervals := make([]interval, 0)
	for len(queue) > 0 {
		spanID := queue[0]
		queue = queue[1:]
		if _, seen := visited[spanID]; seen {
			continue
		}
		visited[spanID] = struct{}{}
		span, found := byID[spanID]
		if !found {
			continue
		}
		queue = append(queue, children[spanID]...)
		if span.Kind != SpanKindClient || span.Service != server.Service {
			continue
		}
		start := maxTime(span.StartTime, server.StartTime)
		end := minTime(span.EndTime, server.EndTime)
		if end.After(start) {
			intervals = append(intervals, interval{start: start, end: end})
		}
	}

	serverDuration := server.EndTime.Sub(server.StartTime)
	wait := unionDuration(intervals)
	if wait > serverDuration {
		wait = serverDuration
	}
	exclusive := serverDuration - wait
	if exclusive < 0 {
		exclusive = 0
	}
	exclusiveRatio := clamp01(float64(exclusive) / float64(serverDuration))
	waitRatio := clamp01(float64(wait) / float64(serverDuration))
	return TraceMeasurement{
		ServerDurationMS:          durationMS(serverDuration),
		DownstreamWaitObservedMS:  durationMS(wait),
		ExclusiveObservedDuration: durationMS(exclusive),
		ExclusiveRatio:            exclusiveRatio,
		DownstreamWaitRatio:       waitRatio,
	}, true
}

func unionDuration(intervals []interval) time.Duration {
	if len(intervals) == 0 {
		return 0
	}
	sort.Slice(intervals, func(left, right int) bool {
		if !intervals[left].start.Equal(intervals[right].start) {
			return intervals[left].start.Before(intervals[right].start)
		}
		return intervals[left].end.Before(intervals[right].end)
	})
	current := intervals[0]
	var total time.Duration
	for _, next := range intervals[1:] {
		if !next.start.After(current.end) {
			if next.end.After(current.end) {
				current.end = next.end
			}
			continue
		}
		total += current.end.Sub(current.start)
		current = next
	}
	return total + current.end.Sub(current.start)
}

func minTime(left, right time.Time) time.Time {
	if left.Before(right) {
		return left
	}
	return right
}

func maxTime(left, right time.Time) time.Time {
	if left.After(right) {
		return left
	}
	return right
}

func durationMS(value time.Duration) float64 {
	return float64(value) / float64(time.Millisecond)
}

func clamp01(value float64) float64 {
	if value < 0 {
		return 0
	}
	if value > 1 {
		return 1
	}
	return value
}
