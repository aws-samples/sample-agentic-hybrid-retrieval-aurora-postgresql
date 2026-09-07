/** A short-lived page read; concurrent consumers share the same request. */
export function cachedRequest<T>(request: () => Promise<T>) {
  let value: T | undefined;
  let receivedAt = 0;
  let pending: Promise<T> | undefined;

  function peek(): T | undefined {
    return Date.now() - receivedAt < 60_000 ? value : undefined;
  }

  function load(): Promise<T> {
    const current = peek();
    if (current !== undefined) return Promise.resolve(current);
    if (pending) return pending;
    pending = request().then((result) => {
      value = result;
      receivedAt = Date.now();
      return result;
    }).finally(() => {
      pending = undefined;
    });
    return pending;
  }

  return { peek, load };
}
