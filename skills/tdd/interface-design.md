# Interface Design for Testability

Good interfaces make testing natural:

1. **Accept dependencies, don't create them**
   - Testable: function processOrder(order, paymentGateway) {}
   - Hard to test: function processOrder(order) { const gateway = new StripeGateway(); }

2. **Return results, don't produce side effects**
   - Testable: function calculateDiscount(cart): Discount {}
   - Hard to test: function applyDiscount(cart): void { cart.total -= discount; }

3. **Small surface area**
   - Fewer methods = fewer tests needed
   - Fewer params = simpler test setup
