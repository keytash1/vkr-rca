package main

import (
	"fmt"
	"os"
	"runtime"
	"strconv"
	"time"
)

var sink uint64

func main() {
	if len(os.Args) != 3 {
		panic("usage: m14-fault-agent cpu|memory duration-seconds")
	}
	duration, err := strconv.Atoi(os.Args[2])
	if err != nil || duration <= 0 {
		panic("bad duration")
	}
	deadline := time.Now().Add(time.Duration(duration) * time.Second)
	switch os.Args[1] {
	case "cpu":
		runtime.GOMAXPROCS(1)
		for time.Now().Before(deadline) {
			for i := uint64(0); i < 10_000_000; i++ {
				sink = sink*1664525 + i + 1013904223
			}
		}
	case "memory":
		memory := make([]byte, 32*1024*1024)
		for index := 0; index < len(memory); index += 4096 {
			memory[index] = byte(index)
		}
		fmt.Fprintln(os.Stderr, "resident-bytes", len(memory))
		runtime.KeepAlive(memory)
		time.Sleep(time.Until(deadline))
		runtime.KeepAlive(memory)
	default:
		panic("unknown mode")
	}
}
