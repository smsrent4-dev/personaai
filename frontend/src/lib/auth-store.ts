import { create } from "zustand";
import { persist } from "zustand/middleware";

export interface CurrentUser {
  id: string;
  email: string;
  full_name: string;
  business_name: string | null;
  role: string;
  is_active: boolean;
  is_email_verified: boolean;
  is_platform_admin: boolean;
}

interface AuthState {
  accessToken: string | null;
  refreshToken: string | null;
  user: CurrentUser | null;
  setTokens: (accessToken: string, refreshToken: string) => void;
  setUser: (user: CurrentUser) => void;
  logout: () => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      accessToken: null,
      refreshToken: null,
      user: null,
      setTokens: (accessToken, refreshToken) => set({ accessToken, refreshToken }),
      setUser: (user) => set({ user }),
      logout: () => set({ accessToken: null, refreshToken: null, user: null }),
    }),
    { name: "personaai-auth" }
  )
);
