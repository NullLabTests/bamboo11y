import { useCallback, useEffect, useEffectEvent, useState } from "react";

import { ApiError } from "../api/client";

export interface ResourceState<T> {
  data: T | null;
  error: ApiError | null;
  loading: boolean;
  reload: () => void;
}

interface Snapshot<T> {
  key: string;
  data: T | null;
  error: ApiError | null;
  loading: boolean;
}

/**
 * Fetch a single API resource. The loader receives an AbortSignal, and stale responses
 * are ignored so filter changes cannot race each other in the UI.
 */
export function useResource<T>(
  key: string,
  loader: (signal: AbortSignal) => Promise<T>,
): ResourceState<T> {
  const [snapshot, setSnapshot] = useState<Snapshot<T>>({
    key,
    data: null,
    error: null,
    loading: true,
  });
  const [nonce, setNonce] = useState(0);
  const load = useEffectEvent(loader);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;

    load(controller.signal)
      .then((value) => {
        if (active) {
          setSnapshot({ key, data: value, error: null, loading: false });
        }
      })
      .catch((cause: unknown) => {
        if (!active || (cause instanceof DOMException && cause.name === "AbortError")) return;
        setSnapshot({
          key,
          data: null,
          error:
            cause instanceof ApiError
              ? cause
              : new ApiError("The dashboard could not load this view.", { status: 0 }),
          loading: false,
        });
      });

    return () => {
      active = false;
      controller.abort();
    };
  }, [key, nonce]);

  const reload = useCallback(() => {
    setSnapshot((current) => ({ ...current, error: null, loading: true }));
    setNonce((value) => value + 1);
  }, []);

  // A key change makes the previous snapshot stale immediately, before the effect runs.
  const isCurrent = snapshot.key === key;
  return {
    data: isCurrent ? snapshot.data : null,
    error: isCurrent ? snapshot.error : null,
    loading: !isCurrent || snapshot.loading,
    reload,
  };
}
