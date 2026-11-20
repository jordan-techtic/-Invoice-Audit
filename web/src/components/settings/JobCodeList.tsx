"use client";

import { useEffect, useState } from "react";
import { api, type VmrsCodeRow } from "@/lib/api";

/** A <datalist> of the job codes the app knows. Point an input at it with list="job-codes". */
export default function JobCodeList({ cid }: { cid: string }) {
  const [codes, setCodes] = useState<VmrsCodeRow[]>([]);
  useEffect(() => { api.vmrsCodes(cid).then(setCodes).catch(() => undefined); }, [cid]);
  return <datalist id="job-codes">{codes.map((c) => <option key={c.code} value={c.code}>{c.component}</option>)}</datalist>;
}
