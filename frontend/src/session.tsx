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
};

const STORAGE_KEY = "excon-session";

export function readStored(): StoredSession {
  if (typeof window === "undefined") {
    return { seller: null, lead: null };
  }
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return { seller: null, lead: null };
    const parsed = JSON.parse(raw) as StoredSession;
    return {
      seller: parsed.seller ?? null,
      lead: parsed.lead ?? null,
    };
  } catch {
    return { seller: null, lead: null };
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

function writeStored(seller: SellerProfile | null, lead: LeadTarget | null) {
  const payload: StoredSession = {
    seller: toStoredSeller(seller),
    lead,
  };
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
}

type SessionValue = {
  seller: SellerProfile | null;
  lead: LeadTarget | null;
  setSeller: (seller: SellerProfile) => void;
  setLead: (lead: LeadTarget) => void;
  resetLead: () => void;
};

const SessionContext = createContext<SessionValue | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const initial = readStored();
  const [seller, setSellerState] = useState<SellerProfile | null>(() =>
    fromStoredSeller(initial.seller),
  );
  const [lead, setLeadState] = useState<LeadTarget | null>(() => initial.lead);

  const setSeller = useCallback((next: SellerProfile) => {
    setSellerState(next);
    setLeadState((currentLead) => {
      writeStored(next, currentLead);
      return currentLead;
    });
  }, []);

  const setLead = useCallback((next: LeadTarget) => {
    setLeadState(next);
    setSellerState((currentSeller) => {
      writeStored(currentSeller, next);
      return currentSeller;
    });
  }, []);

  const resetLead = useCallback(() => {
    setLeadState(null);
    setSellerState((currentSeller) => {
      writeStored(currentSeller, null);
      return currentSeller;
    });
  }, []);

  const value = useMemo(
    () => ({
      seller,
      lead,
      setSeller,
      setLead,
      resetLead,
    }),
    [seller, lead, setSeller, setLead, resetLead],
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
