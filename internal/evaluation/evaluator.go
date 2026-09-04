package evaluation

import "vkr-rca/internal/diagnosis"

type Result struct {
	GroundTruth    string  `json:"ground_truth"`
	Found          bool    `json:"found"`
	Rank           int     `json:"rank"`
	ACAt1          int     `json:"ac_at_1"`
	ACAt3          int     `json:"ac_at_3"`
	ReciprocalRank float64 `json:"reciprocal_rank"`
}

// Evaluate applies ground truth only after ranking has completed.
func Evaluate(ranking diagnosis.Ranking, groundTruth string) Result {
	result := Result{GroundTruth: groundTruth}
	for index, candidate := range ranking {
		if candidate.Service != groundTruth {
			continue
		}
		rank := candidate.Rank
		if rank <= 0 {
			rank = index + 1
		}
		result.Found = true
		result.Rank = rank
		if rank <= 1 {
			result.ACAt1 = 1
		}
		if rank <= 3 {
			result.ACAt3 = 1
		}
		result.ReciprocalRank = 1 / float64(rank)
		return result
	}
	return result
}
