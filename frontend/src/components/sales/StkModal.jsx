import { Alert, Button, Field, Input, Modal } from "../ui";
import { money } from "../../lib/format";

export default function StkModal({ target, phone, onPhoneChange, status, saving, onSend, onClose }) {
  return (
    <Modal
      open={Boolean(target)}
      onClose={onClose}
      title="Send M-Pesa prompt"
      subtitle={
        target
          ? `Receipt ${target.receipt.id.slice(0, 8).toUpperCase()} · KES ${money(target.amount)}`
          : ""
      }
      size="sm"
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Close
          </Button>
          <Button variant="brand" loading={saving} onClick={onSend} icon="phone">
            Send prompt
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
      {status && (
        <Alert tone={status.type} className="mt-3">
          {status.message}
        </Alert>
      )}
    </Modal>
  );
}
