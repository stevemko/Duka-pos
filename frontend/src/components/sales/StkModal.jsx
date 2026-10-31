import { Button, Field, Input, Modal } from "../ui";
import PaymentStatusBanner from "./PaymentStatusBanner";
import { money } from "../../lib/format";

export default function StkModal({
  target,
  phone,
  onPhoneChange,
  status,
  saving,
  checking,
  onCheck,
  onSend,
  onClose,
}) {
  const waiting = status?.state === "waiting";

  return (
    <Modal
      open={Boolean(target)}
      onClose={onClose}
      title={waiting ? "Waiting for the customer" : "Send M-Pesa prompt"}
      subtitle={
        target
          ? `Receipt ${target.receipt.id.slice(0, 8).toUpperCase()} · KES ${money(target.amount)}`
          : ""
      }
      size="sm"
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            {waiting ? "Close while waiting" : "Close"}
          </Button>
          <Button variant="brand" loading={saving} disabled={waiting} onClick={onSend} icon="phone">
            {status ? "Send prompt again" : "Send prompt"}
          </Button>
        </>
      }
    >
      <Field label="M-Pesa phone" required hint="Safaricom number, e.g. 0712345678.">
        <Input
          type="tel"
          value={phone}
          onChange={(event) => onPhoneChange(event.target.value)}
          placeholder="07XXXXXXXX"
          autoFocus
        />
      </Field>
      <div className="mt-3">
        <PaymentStatusBanner
          status={status}
          checking={checking}
          onCheck={status?.state === "not_sent" ? null : onCheck}
        />
        {!status && (
          <p className="text-xs text-ink-500">
            Press Send prompt and the customer gets an M-Pesa request on their phone. This dialog
            keeps checking, and the receipt below the till repeats the same message if you close it.
          </p>
        )}
      </div>
    </Modal>
  );
}
