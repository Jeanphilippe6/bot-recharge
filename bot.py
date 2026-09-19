<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Gestion de Commande - Preuve de Paiement</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 20px; line-height: 1.6; }
    .card { border: 1px solid #ccc; padding: 20px; border-radius: 8px; margin-bottom: 20px; max-width: 550px; }
    .admin-panel { background-color: #f9f9f9; border-left: 5px solid #007bff; }
    .client-panel { background-color: #ffffff; border-left: 5px solid #28a745; }
    .btn { background-color: #007bff; color: white; padding: 10px 15px; border: none; border-radius: 4px; cursor: pointer; margin-right: 5px; margin-top: 5px; }
    .btn-warning { background-color: #ffc107; color: #212529; }
    .btn-success { background-color: #28a745; }
    .btn-danger { background-color: #dc3545; }
    .btn:hover { opacity: 0.9; }
    .status-badge { display: inline-block; padding: 5px 10px; background-color: #e2e3e5; border-radius: 4px; font-weight: bold; }
    .alert { padding: 12px; border-radius: 4px; margin-bottom: 15px; }
    .alert-info { background-color: #cce5ff; color: #004085; }
    .alert-warning { background-color: #fff3cd; color: #856404; }
    .alert-success { background-color: #d4edda; color: #155724; }
    .alert-danger { background-color: #f8d7da; color: #721c24; }
    .hidden { display: none; }
    .proof-preview { width: 100%; max-height: 150px; background: #eee; display: flex; align-items: center; justify-content: center; margin: 10px 0; border: 1px dashed #aaa; }
  </style>
</head>
<body>

  <!-- INTERFACE ADMINISTRATEUR -->
  <div class="card admin-panel">
    <h2>🛠️ Panneau d'administration</h2>
    <p><strong>Client :</strong> Jean Dupont</p>
    <p><strong>Adresse client :</strong> <span id="admin-address-text">Abidjan, Cocody Blockhauss</span></p>
    <p><strong>Numéro Mobile Money :</strong> <span id="admin-phone-text">0700000000</span></p>
    <p><strong>Preuve de paiement :</strong></p>
    <div class="proof-preview" id="admin-proof-display">📷 [ Capture écran reçue ]</div>
    
    <p><strong>Statut :</strong> <span id="admin-status" class="status-badge">Preuve reçue - En attente</span></p>

    <hr style="margin: 15px 0;">

    <div id="admin-step-start-verify">
      <button class="btn btn-warning" onclick="adminStartVerification()">
        🔍 Lancer la vérification
      </button>
    </div>

    <div id="admin-step-decision" class="hidden">
      <div class="alert alert-warning" style="margin-top: 10px;">
        ⚙️ Vérification en cours... Veuillez contrôler la preuve puis valider ou rejeter.
      </div>
      <button class="btn btn-success" onclick="adminMakeDecision(true)">
        ✅ Valider la commande
      </button>
      <button class="btn btn-danger" onclick="adminMakeDecision(false)">
        ❌ Rejeter la commande
      </button>
    </div>
  </div>

  <!-- INTERFACE CLIENT -->
  <div class="card client-panel">
    <h2>🛒 Espace Client</h2>

    <div id="client-step-upload">
      <h3>Étape : Transmettre la preuve de paiement</h3>
      <form onsubmit="submitProof(event)">
        <label for="proof-file">Capture d'écran du transfert Mobile Money :</label><br>
        <input type="file" id="proof-file" required style="margin: 10px 0;"><br>
        <button type="submit" class="btn">Envoyer la preuve de paiement</button>
      </form>
    </div>

    <div id="client-step-waiting" class="hidden">
      <div class="alert alert-info">
        ⏳ <strong>Preuve envoyée !</strong><br>
        L'administrateur va vérifier votre paiement sous peu.
      </div>
    </div>

    <div id="client-step-verifying" class="hidden">
      <div class="alert alert-warning">
        🔍 <strong>Vérification en cours...</strong><br>
        L'administrateur examine actuellement votre preuve de paiement.
      </div>
    </div>

    <div id="client-step-success" class="hidden">
      <div class="alert alert-success">
        🎉 <strong>Commande Validée !</strong><br>
        Votre paiement a été confirmé avec succès. La livraison sera effectuée à votre adresse.
      </div>
    </div>

    <div id="client-step-failed" class="hidden">
      <div class="alert alert-danger">
        ❌ <strong>Commande Rejetée</strong><br>
        La preuve de paiement est invalide ou non reçue. Veuillez soumettre une nouvelle preuve.
      </div>
      <button class="btn" onclick="retryUpload()">Renvoyer une preuve</button>
    </div>
  </div>

  <script>
    function submitProof(event) {
      event.preventDefault();
      document.getElementById("client-step-upload").classList.add("hidden");
      document.getElementById("client-step-waiting").classList.remove("hidden");
      document.getElementById("admin-status").innerText = "Preuve de paiement reçue";
    }

    function adminStartVerification() {
      document.getElementById("admin-step-start-verify").classList.add("hidden");
      document.getElementById("admin-step-decision").classList.remove("hidden");
      document.getElementById("admin-status").innerText = "Vérification en cours...";
      document.getElementById("admin-status").style.backgroundColor = "#fff3cd";

      document.getElementById("client-step-waiting").classList.add("hidden");
      document.getElementById("client-step-verifying").classList.remove("hidden");
    }

    function adminMakeDecision(isValidated) {
      document.getElementById("admin-step-decision").classList.add("hidden");
      document.getElementById("client-step-verifying").classList.add("hidden");

      if (isValidated) {
        document.getElementById("admin-status").innerText = "✅ Commande validée";
        document.getElementById("admin-status").style.backgroundColor = "#d4edda";
        document.getElementById("client-step-success").classList.remove("hidden");
      } else {
        document.getElementById("admin-status").innerText = "❌ Commande rejetée";
        document.getElementById("admin-status").style.backgroundColor = "#f8d7da";
        document.getElementById("client-step-failed").classList.remove("hidden");
      }
    }

    function retryUpload() {
      document.getElementById("client-step-failed").classList.add("hidden");
      document.getElementById("client-step-upload").classList.remove("hidden");
      document.getElementById("admin-step-start-verify").classList.remove("hidden");
      document.getElementById("admin-status").innerText = "En attente d'une nouvelle preuve";
      document.getElementById("admin-status").style.backgroundColor = "#e2e3e5";
    }
  </script>

</body>
</html>
