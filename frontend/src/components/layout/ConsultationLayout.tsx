import type { ReactNode } from "react";
import { Col, Container, Row } from "react-bootstrap";

interface ConsultationLayoutProps {
  header: ReactNode;
  banner?: ReactNode;
  left: ReactNode;
  center: ReactNode;
  right: ReactNode;
}

export default function ConsultationLayout({ header, banner, left, center, right }: ConsultationLayoutProps) {
  return (
    <Container fluid className="scribe-layout px-3 py-3">
      <Row className="mb-3">
        <Col xs={12}>{header}</Col>
      </Row>
      {banner && (
        <Row className="mb-3">
          <Col xs={12}>{banner}</Col>
        </Row>
      )}
      <Row className="g-3 align-items-start">
        <Col xs={12} lg={3}>
          {left}
        </Col>
        <Col xs={12} lg={5}>
          {center}
        </Col>
        <Col xs={12} lg={4}>
          {right}
        </Col>
      </Row>
    </Container>
  );
}
