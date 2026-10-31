import { useEffect, useState } from "react";
import { receiptsApi, apiErrorMessage } from "../../api/client";
import { useAuth } from "../../auth/AuthContext";
import Icon from "../Icon";
import { cleanMoney, money } from "../../lib/format";
import { Alert, Button, Field, Input, Modal, Select } from "../ui";

export default function SettlePaymentModal({ receipt, onClose, onSaved }) {
  const { shop } = useAuth();
  const [amount, setAmount] = useState("");
  const [method, setMethod] = useState("cash");
  const [reference, setReference] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setAmount(receipt ? String(receipt.balance) : "");
    setMethod("cash");
    setReference("");
    setError("");
  }, [receipt]);

  async function save() {
    const value = Number(amount);
    if (!Number.isFinite(value) || value <= 0 || value > Number(receipt.balance)) {
      setError("Enter an amount within the outstanding balance.");
      return;
    }
    if (method === "mpesa_paybill" && !reference.trim()) {
      setError("Enter the M-Pesa confirmation code for this Paybill payment.");
      return;
    }
    setSaving(true);
    setError("");
    try {
      const updated = await receiptsApi.addPayment(receipt.id, {
        amount: value.toFixed(2),
        method,
        reference: reference.trim(),
      });
      onSaved(updated);
    } catch (requestError) {
      setError(apiErrorMessage(requestError, "Could not record this payment."));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      open={Boolean(receipt)}
      onClose={onClose}
      title="Record payment"
      subtitle={
        receipt
          ? `${receipt.customer_name || receipt.customer_phone || "Walk-in"} · balance KES ${money(receipt.balance)}`
          : ""
      }
      size="sm"
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="brand" loading={saving} onClick={save}>
            Save payment
          </Button>
        </>
      }
    >
      <div className="grid grid-cols-2 gap-3">
        <Field label="Amount (KES)" required>
          <Input
            inputMode="decimal"
            value={amount}
            onChange={(event) => {
              setAmount(cleanMoney(event.target.value));
              setError("");
            }}
            autoFocus
          />
        </Field>
        <Field label="Method">
          <Select
            value={method}
            onChange={(event) => {
              setMethod(event.target.value);
              setReference("");
              setError("");
            }}
          >
            <option value="cash">Cash</option>
            <option value="mpesa_paybill">M-Pesa Paybill</option>
            <option value="mobile_money">Mobile money</option>
            <option value="card">Card</option>
            <option value="bank_transfer">Bank transfer</option>
          </Select>
        </Field>
      </div>

      {method === "mpesa_paybill" && (
        <div className="mt-3 space-y-2 rounded-xl border border-sky-200 bg-sky-50 p-3 text-xs text-sky-900">
          <p className="flex items-start gap-2">
            <Icon name="bank" size={15} className="mt-0.5 shrink-0" />
            <span>
              Paybill <strong>{shop?.paybill || "not configured"}</strong>, account{" "}
              <strong>{receipt?.id.slice(0, 8).toUpperCase()}</strong>.
            </span>
          </p>
          <Field label="Confirmation code" required>
            <Input
              value={reference}
              onChange={(event) => {
                setReference(event.target.value.toUpperCase());
                setError("");
              }}
              placeholder="e.g. SLK7XYZ12A"
              autoComplete="off"
            />
          </Field>
        </div>
      )}
      {error && <Alert tone="error" className="mt-3">{error}</Alert>}
    </Modal>
  );
}
