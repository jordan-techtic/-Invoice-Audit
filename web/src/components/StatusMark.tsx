import { STATUS_LABEL, type ReviewStatus } from "@/lib/api";
import { IconAlert, IconCheck } from "./Icons";

export default function StatusMark({ status }: { status: ReviewStatus }) {
  if (status === "needs_review")
    return <span className="inline-flex items-center gap-1.5 font-medium"><span className="text-money"><IconAlert /></span>{STATUS_LABEL[status]}</span>;
  if (status === "reviewed")
    return <span className="inline-flex items-center gap-1.5 font-medium text-confirmed"><IconCheck />{STATUS_LABEL[status]}</span>;
  return <span className="font-medium text-muted">{STATUS_LABEL[status]}</span>;
}
