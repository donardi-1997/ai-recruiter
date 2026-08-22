import { useEffect, useState } from "react";

import { useParams } from "react-router-dom";

import api from "../api/client";

function CandidateDetail() {
  const { candidate_id } = useParams();

  const [candidate, setCandidate] = useState(null);

  const [evaluations, setEvaluations] = useState([]);

  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      try {
        const candidateResponse = await api.get(`/candidates/${candidate_id}`);

        setCandidate(candidateResponse.data);

        const evaluationResponse = await api.get(
          `/candidates/${candidate_id}/evaluations`,
        );

        setEvaluations(evaluationResponse.data.evaluations || []);
      } catch (error) {
        console.error(error);
      } finally {
        setLoading(false);
      }
    }

    load();
  }, [candidate_id]);

  if (loading) {
    return <p>Cargando candidato...</p>;
  }

  const evaluation = evaluations[0];

  return (
    <div
      style={{
        padding: "40px",
      }}
    >
      <h1>{candidate?.name}</h1>

      <p>{candidate?.filename}</p>

      {evaluation && (
        <>
          <h2>Evaluación IA</h2>

          <h1>{evaluation.match_score}%</h1>

          <h3>{evaluation.recommendation}</h3>

          <h2>Resumen</h2>

          <p>{evaluation.summary}</p>

          <h2>Fortalezas</h2>

          <ul>
            {evaluation.strengths?.map((item, index) => (
              <li key={index}>{item}</li>
            ))}
          </ul>

          <h2>Gaps</h2>

          <ul>
            {evaluation.gaps?.map((item, index) => (
              <li key={index}>{item}</li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

export default CandidateDetail;
