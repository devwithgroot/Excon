import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";

export type SellerIdentity = {
  name: string;
  companyName: string;
  companyWebsite: string;
};

export type LeadTarget = {
  companyName: string;
  companyWebsite?: string;
  companyDomain?: string;
};

export type StoredSession = {
  seller: SellerIdentity | null;
  sellerId: string | null;
  jobId: string | null;
  sellerApproved: boolean;
  lead: LeadTarget | null;
  runId: string | null;
};

const STORAGE_KEY = "excon-session";

const EMPTY: StoredSession = {
  seller: null,
  sellerId: null,
  jobId: null,
  sellerApproved: false,
  lead: null,
  runId: null,
};

export function readStored(): StoredSession {
  if (typeof window === "undefined") return EMPTY;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return EMPTY;
    const parsed = JSON.parse(raw) as Partial<StoredSession>;
    const seller = parsed.seller
      ? {
          name: parsed.seller.name ?? "",
          companyName: parsed.seller.companyName ?? "",
          companyWebsite: parsed.seller.companyWebsite ?? "",
        }
      : null;
    return {
      seller,
      sellerId: parsed.sellerId ?? null,
      jobId: parsed.jobId ?? null,
      sellerApproved: parsed.sellerApproved ?? false,
      lead: parsed.lead ?? null,
      runId: parsed.runId ?? null,
    };
  } catch {
    return EMPTY;
  }
}

type SessionValue = StoredSession & {
  startOnboarding: (seller: SellerIdentity, sellerId: string, jobId: string) => void;
  setSellerRecord: (sellerId: string, approved: boolean) => void;
  setLead: (lead: LeadTarget) => void;
  setRunId: (runId: string | null) => void;
  resetLead: () => void;
};

const SessionContext = createContext<SessionValue | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<StoredSession>(readStored);

  const update = useCallback((change: (current: StoredSession) => StoredSession) => {
    setState((current) => {
      const next = change(current);
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
      return next;
    });
  }, []);

  const startOnboarding = useCallback(
    (seller: SellerIdentity, sellerId: string, jobId: string) =>
      update((current) => ({
        ...current,
        seller,
        sellerId,
        jobId,
        sellerApproved: false,
        runId: null,
      })),
    [update],
  );

  const setSellerRecord = useCallback(
    (sellerId: string, approved: boolean) =>
      update((current) => ({ ...current, sellerId, sellerApproved: approved })),
    [update],
  );

  const setLead = useCallback(
    (lead: LeadTarget) => update((current) => ({ ...current, lead, runId: null })),
    [update],
  );

  const setRunId = useCallback(
    (runId: string | null) => update((current) => ({ ...current, runId })),
    [update],
  );

  const resetLead = useCallback(
    () => update((current) => ({ ...current, lead: null, runId: null })),
    [update],
  );

  const value = useMemo(
    () => ({ ...state, startOnboarding, setSellerRecord, setLead, setRunId, resetLead }),
    [state, startOnboarding, setSellerRecord, setLead, setRunId, resetLead],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession() {
  const session = useContext(SessionContext);
  if (!session) {
    throw new Error("useSession must be used inside SessionProvider");
  }
  return session;
}
