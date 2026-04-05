# When to Mock

Mock at **system boundaries** only:
- External APIs (payment, email, etc.)
- Databases (sometimes - prefer test DB)
- Time/randomness
- File system (sometimes)

Don't mock:
- Your own classes/modules
- Internal collaborators
- Anything you control

## Designing for Mockability

At system boundaries, use dependency injection and prefer SDK-style interfaces over generic fetchers.

SDK approach (GOOD): Each function is independently mockable
  const api = {
    getUser: (id) => fetch(`/users/${id}`),
    getOrders: (userId) => fetch(`/users/${userId}/orders`),
    createOrder: (data) => fetch('/orders', { method: 'POST', body: data }),
  };

Generic approach (BAD): Mocking requires conditional logic inside the mock
  const api = {
    fetch: (endpoint, options) => fetch(endpoint, options),
  };

Benefits: each mock returns one specific shape, no conditional logic in test setup, easier to see which endpoints a test exercises, type safety per endpoint.
