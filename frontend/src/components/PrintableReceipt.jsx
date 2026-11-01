import { useAuth } from "../auth/AuthContext";

const SHOP_NAME = import.meta.env.VITE_SHOP_NAME || "Greenlight LED Accessories";
const SHOP_WEBSITE = (import.meta.env.VITE_SHOP_WEBSITE || "").trim();
const SHOP_PHONE = (import.meta.env.VITE_SHOP_PHONE || "").trim();

export default function PrintableReceipt({ receipt, title = "SALES RECEIPT" }) {
  const { shop } = useAuth();
  const name = shop?.name || SHOP_NAME;
  const website = shop?.website || SHOP_WEBSITE;
  const phone = shop?.phone || SHOP_PHONE;
  const paybill = shop?.paybill || "";
  const balance = Number(receipt.balance);
  const returns = receipt.returns || [];
  const returnedValue = Number(receipt.returned_total || 0);
  const refundedValue = Number(receipt.refunded_total || 0);

  return (
    <article className="print-receipt" aria-label="Receipt for printing">
      <header className="receipt-center">
        <h1>{name}</h1>
        <p>{title}</p>
        {phone && <p>Tel: {phone}</p>}
        {website && <p>{website}</p>}
      </header>
      <div className="receipt-rule" />
      <p>Receipt: {receipt.id}</p>
      <p>Date: {new Date(receipt.created_at).toLocaleString()}</p>
      <p>Branch: {receipt.branch_name || "Main shop"}</p>
      <p>Served by: {receipt.created_by_name || "Counter"}</p>
      {(receipt.customer_name || receipt.customer_phone) && (
        <p>Customer: {receipt.customer_name || receipt.customer_phone}</p>
      )}
      <div className="receipt-rule" />
      <table>
        <thead>
          <tr>
            <th>Item</th>
            <th>Qty</th>
            <th>Total</th>
          </tr>
        </thead>
        <tbody>
          {receipt.items.map((item) => (
            <tr key={item.id}>
              <td>
                {item.product_name}
                <small>{` @ KES ${item.price_sold_at}`}</small>
              </td>
              <td>{item.quantity}</td>
              <td>KES {item.total}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {returns.length > 0 && (
        <>
          <div className="receipt-rule" />
          <p>
            <strong>Returned</strong>
          </p>
          {returns.map((entry) => (
            <div key={entry.id}>
              {entry.items.map((item) => (
                <p key={item.id} className="receipt-row">
                  <span>
                    {item.product_name} <small>{`× ${item.quantity}`}</small>
                    {entry.reason ? ` (${entry.reason})` : ""}
                  </span>
                  <span>KES {item.total}</span>
                </p>
              ))}
            </div>
          ))}
        </>
      )}
      <div className="receipt-rule" />
      <p className="receipt-row">
        <strong>Total</strong>
        <strong>KES {receipt.total}</strong>
      </p>
      {returnedValue > 0 && (
        <p className="receipt-row">
          <span>Returned</span>
          <span>KES {receipt.returned_total}</span>
        </p>
      )}
      {returnedValue > 0 && (
        <p className="receipt-row">
          <span>Bill after returns</span>
          <span>KES {receipt.net_total}</span>
        </p>
      )}
      <p className="receipt-row">
        <span>Paid</span>
        <span>KES {receipt.amount_paid}</span>
      </p>
      {refundedValue > 0 && (
        <p className="receipt-row">
          <span>Handed back</span>
          <span>KES {receipt.refunded_total}</span>
        </p>
      )}
      <p className="receipt-row">
        <span>Balance</span>
        <span>KES {receipt.balance}</span>
      </p>
      <p className="receipt-row">
        <span>Status</span>
        <span>{receipt.payment_status.replaceAll("_", " ")}</span>
      </p>
      {balance > 0 && paybill && (
        <p>
          Pay balance to Paybill {paybill}, account {receipt.id.slice(0, 8).toUpperCase()}.
        </p>
      )}
      {receipt.payments.length > 0 && (
        <>
          <div className="receipt-rule" />
          <p>
            <strong>Payments</strong>
          </p>
          {receipt.payments.map((payment) => (
            <p key={payment.id} className="receipt-row">
              <span>
                {payment.method.replaceAll("_", " ")}
                {payment.reference ? ` · ${payment.reference}` : ""}
                {payment.status !== "succeeded" ? ` (${payment.status})` : ""}
              </span>
              <span>KES {payment.amount}</span>
            </p>
          ))}
        </>
      )}
      <div className="receipt-rule" />
      <p className="receipt-center">Thank you for shopping with us.</p>
    </article>
  );
}
