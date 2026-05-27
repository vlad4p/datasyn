export type ChatMsg = {
  id: string;
  role: "user" | "assistant";
  content: string;
  subagentContent?: string;
  requestId?: string;
  streaming?: boolean;
  activity?: string | null;
};
