import { createContext } from "react";
import type { Project } from "./types";

export interface AppState {
  project: Project | null;
  /** Bumped by Actualizar; every query depends on it so the whole view reloads. */
  generation: number;
  changed: boolean;
  refreshing: boolean;
  observe: (stateId: string) => void;
  markChanged: () => void;
  refresh: () => Promise<void>;
}
export const AppContext = createContext<AppState>({
  project: null, generation: 0, changed: false, refreshing: false, observe: () => {}, markChanged: () => {}, refresh: async () => {},
});
