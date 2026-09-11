// eslint-disable-next-line no-unused-vars
import React, { useEffect } from "react";
import { useSearchParams } from "react-router-dom";

import RankingView from "./RankingView.jsx";

function selectRequestedJob(requestedJobId) {
  if (!requestedJobId) return true;

  const select = document.querySelector(".ranking-job-select");
  if (!select) return false;

  const optionExists = Array.from(select.options || []).some(
    (option) => option.value === requestedJobId,
  );
  if (!optionExists) return false;
  if (select.value === requestedJobId) return true;

  const valueSetter = Object.getOwnPropertyDescriptor(
    HTMLSelectElement.prototype,
    "value",
  )?.set;
  if (valueSetter) valueSetter.call(select, requestedJobId);
  else select.value = requestedJobId;

  select.dispatchEvent(new Event("change", { bubbles: true }));
  return true;
}

export default function Ranking() {
  const [searchParams] = useSearchParams();
  const requestedJobId = searchParams.get("job_id") || "";

  useEffect(() => {
    if (!requestedJobId) return undefined;

    if (selectRequestedJob(requestedJobId)) return undefined;

    const observer = new MutationObserver(() => {
      if (selectRequestedJob(requestedJobId)) observer.disconnect();
    });
    observer.observe(document.body, { childList: true, subtree: true });

    return () => observer.disconnect();
  }, [requestedJobId]);

  return <RankingView />;
}
