package main

import (
	"bufio"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"os"

	"vkr-rca/internal/externalrca"
)

func main() {
	ndjson := flag.Bool("ndjson", false, "read one input header followed by normalized span records")
	flag.Parse()
	var input externalrca.Input
	if *ndjson {
		readNDJSON(&input)
	} else if err := json.NewDecoder(os.Stdin).Decode(&input); err != nil {
		fatal(err)
	}
	output, err := externalrca.Process(input)
	if err != nil {
		fatal(err)
	}
	encoder := json.NewEncoder(os.Stdout)
	encoder.SetEscapeHTML(false)
	if err := encoder.Encode(output); err != nil {
		fatal(err)
	}
}

func readNDJSON(input *externalrca.Input) {
	reader := bufio.NewReaderSize(os.Stdin, 1024*1024)
	header, err := reader.ReadBytes('\n')
	if err != nil && err != io.EOF {
		fatal(err)
	}
	if err := json.Unmarshal(header, input); err != nil {
		fatal(fmt.Errorf("decode header: %w", err))
	}
	decoder := json.NewDecoder(reader)
	for {
		var span externalrca.Span
		if err := decoder.Decode(&span); err != nil {
			if err == io.EOF {
				break
			}
			fatal(fmt.Errorf("decode span: %w", err))
		}
		input.Spans = append(input.Spans, span)
	}
}

func fatal(err error) {
	fmt.Fprintln(os.Stderr, err)
	os.Exit(1)
}
