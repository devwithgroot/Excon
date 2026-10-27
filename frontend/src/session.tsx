import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";

export type SellerProfile = {
  name: string;
  companyName: string;
  companyWebsite: string;
  documents: File[];
};

export type LeadTarget = {
  companyName: string;
  companyWebsite?: string;
  companyDomain?: string;
};

export type StoredSeller = {
  name: string;
  companyName: string;
  companyWebsite: string;
  documentNames: string[];
};

export type StoredSession = {
  seller: StoredSeller | null;
  lead: LeadTarget | null;
  sellerId: string | null;
  sellerApproved: boolean;
  runId: string | null;
};

const STORAGE_KEY = "excon-session";

export function readStored(): StoredSession {
  if (typeof window === "undefined") {
    return { seller: null, lead: null, sellerId: null, sellerApproved: false, runId: null };
  }
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return { seller: null, lead: null, sellerId: null, sellerApproved: false, runId: null };
    const parsed = JSON.parse(raw) as StoredSession;
    return {
      seller: parsed.seller ?? null,
      lead: parsed.lead ?? null,
      sellerId: parsed.sellerId ?? null,
      sellerApproved: parsed.sellerApproved ?? false,
      runId: parsed.runId ?? null,
    };
  } catch {
    return { seller: null, lead: null, sellerId: null, sellerApproved: false, runId: null };
  }
}

function toStoredSeller(seller: SellerProfile | null): StoredSeller | null {
  if (!seller) return null;
  return {
    name: seller.name,
    companyName: seller.companyName,
    companyWebsite: seller.companyWebsite,
    documentNames: seller.documents.map((file) => file.name),
  };
}

export function fromStoredSeller(stored: StoredSeller | null): SellerProfile | null {
  if (!stored) return null;
  return {
    name: stored.name,
    companyName: stored.companyName,
    companyWebsite: stored.companyWebsite,
    documents: [],
  };
}

function writeStored(
  seller: SellerProfile | null,
  lead: LeadTarget | null,
  sellerId: string | null,
  sellerApproved: boolean,
  runId: string | null,
) {
  const payload: StoredSession = {
    seller: toStoredSeller(seller),
    lead,
    sellerId,
    sellerApproved,
    runId,
  };
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
}

type SessionValue = {
  seller: SellerProfile | null;
  lead: LeadTarget | null;
  sellerId: string | null;
  sellerApproved: boolean;
  runId: string | null;
  setSeller: (seller: SellerProfile) => void;
  setSellerRecord: (sellerId: string, approved: boolean) => void;
  setLead: (lead: LeadTarget) => void;
  setRunId: (runId: string | null) => void;
  resetLead: () => void;
};

const SessionContext = createContext<SessionValue | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const initial = readStored();
  const [seller, setSellerState] = useState<SellerProfile | null>(() =>
    fromStoredSeller(initial.seller),
  );
  const [lead, setLeadState] = useState<LeadTarget | null>(() => initial.lead);
  const [sellerId, setSellerIdState] = useState<string | null>(() => initial.sellerId);
  const [sellerApproved, setSellerApprovedState] = useState(initial.sellerApproved);
  const [runId, setRunIdState] = useState<string | null>(() => initial.runId);

  const setSeller = useCallback((next: SellerProfile) => {
    setSellerState(next);
    setSellerIdState(null);
    setSellerApprovedState(false);
    setRunIdState(null);
    setLeadState((currentLead) => {
      writeStored(next, currentLead, null, false, null);
      return currentLead;
    });
  }, []);

  const setSellerRecord = useCallback((nextId: string, approved: boolean) => {
    setSellerIdState(nextId);
    setSellerApprovedState(approved);
    setSellerState((currentSeller) => {
      setLeadState((currentLead) => {
        setRunIdState((currentRun) => {
          writeStored(currentSeller, currentLead, nextId, approved, currentRun);
          return currentRun;
        });
        return currentLead;
      });
      return currentSeller;
    });
  }, []);

  const setLead = useCallback((next: LeadTarget) => {
    setLeadState(next);
    setRunIdState(null);
    setSellerState((currentSeller) => {
      setSellerIdState((currentId) => {
        setSellerApprovedState((approved) => {
          writeStored(currentSeller, next, currentId, approved, null);
          return approved;
        });
        return currentId;
      });
      return currentSeller;
    });
  }, []);

  const setRunId = useCallback((next: string | null) => {
    setRunIdState(next);
    setSellerState((currentSeller) => {
      setLeadState((currentLead) => {
        setSellerIdState((currentId) => {
          setSellerApprovedState((approved) => {
            writeStored(currentSeller, currentLead, currentId, approved, next);
            return approved;
          });
          return currentId;
        });
        return currentLead;
      });
      return currentSeller;
    });
  }, []);

  const resetLead = useCallback(() => {
    setLeadState(null);
    setRunIdState(null);
    setSellerState((currentSeller) => {
      setSellerIdState((currentId) => {
        setSellerApprovedState((approved) => {
          writeStored(currentSeller, null, currentId, approved, null);
          return approved;
        });
        return currentId;
      });
      return currentSeller;
    });
  }, []);

  const value = useMemo(
    () => ({
      seller,
      lead,
      sellerId,
      sellerApproved,
      runId,
      setSeller,
      setSellerRecord,
      setLead,
      setRunId,
      resetLead,
    }),
    [
      seller,
      lead,
      sellerId,
      sellerApproved,
      runId,
      setSeller,
      setSellerRecord,
      setLead,
      setRunId,
      resetLead,
    ],
  );

  return (
    <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
  );
}

export function useSession() {
  const session = useContext(SessionContext);
  if (!session) {
    throw new Error("useSession must be used inside SessionProvider");
  }
  return session;
}
